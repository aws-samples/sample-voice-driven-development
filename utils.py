"""
Utility functions for the Audio Transcription App

This module contains all business logic and AWS service interactions
for S3 operations, Transcribe operations, Bedrock operations, and
file system operations.
"""

import boto3
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Tuple
from botocore.exceptions import ClientError


def generate_unique_filename() -> str:
    """
    Generate unique filename with timestamp for audio files
    
    Returns:
        Unique filename in format: audio_recording_YYYYMMDD_HHMMSS_microseconds.wav
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"audio_recording_{timestamp}.wav"


def resolve_bedrock_region(model_id: str) -> str:
    """
    Resolve the AWS region to use for a Bedrock model ID.

    Bedrock cross-region inference profiles are namespaced by geography:
    - "us.*" profiles live in US regions (we use us-east-1)
    - "eu.*" profiles live in EU regions (we use eu-west-1)
    - "apac.*" profiles live in APAC regions (we use ap-northeast-1)

    An explicit AWS_REGION env var always wins.

    Args:
        model_id: Bedrock model ID or inference profile ID.

    Returns:
        AWS region string suitable for boto3 clients.
    """
    explicit = os.environ.get("AWS_REGION") or os.environ.get("BEDROCK_REGION")
    if explicit:
        return explicit

    if not model_id:
        return "us-east-1"

    prefix = model_id.split(".", 1)[0].lower()
    if prefix == "eu":
        return "eu-west-1"
    if prefix == "apac":
        return "ap-northeast-1"
    # "us" and anything else falls back to us-east-1.
    return "us-east-1"


def process_audio_input(recorded_audio, uploaded_file) -> bytes:
    """
    Process audio input from either microphone recording or file upload
    
    Args:
        recorded_audio: Audio data from st.audio_input (BytesIO object or None)
        uploaded_file: Audio file from st.file_uploader (UploadedFile object or None)
        
    Returns:
        Audio data as bytes
        
    Raises:
        ValueError: If no audio input is provided or both inputs are provided
        Exception: For other processing errors
    """
    # Check that exactly one input method is provided
    has_recording = recorded_audio is not None
    has_upload = uploaded_file is not None
    
    if not has_recording and not has_upload:
        raise ValueError("No audio input provided. Please either record audio or upload a .wav file.")
    
    if has_recording and has_upload:
        raise ValueError("Multiple audio inputs provided. Please use either microphone recording or file upload, not both.")
    
    try:
        if has_recording:
            # Process microphone recording (st.audio_input returns BytesIO object)
            if hasattr(recorded_audio, 'getvalue'):
                # BytesIO object - get the bytes
                audio_bytes = recorded_audio.getvalue()
            else:
                # Already bytes
                audio_bytes = recorded_audio
            
            if not audio_bytes or len(audio_bytes) == 0:
                raise ValueError("Recorded audio is empty. Please record some audio before submitting.")
            
            return audio_bytes
            
        elif has_upload:
            # Process uploaded file (st.file_uploader returns UploadedFile object)
            if not hasattr(uploaded_file, 'read'):
                raise ValueError("Invalid uploaded file format. Expected file-like object.")
            
            # Read the file content
            audio_bytes = uploaded_file.read()
            
            if not audio_bytes or len(audio_bytes) == 0:
                raise ValueError("Uploaded file is empty. Please upload a valid .wav file.")
            
            # Validate file size (reasonable limits)
            max_size = 100 * 1024 * 1024  # 100MB limit
            if len(audio_bytes) > max_size:
                raise ValueError(f"Uploaded file is too large ({len(audio_bytes)} bytes). Maximum size is {max_size} bytes.")
            
            return audio_bytes
            
    except ValueError:
        # Re-raise ValueError as-is
        raise
    except Exception as e:
        raise Exception(f"Unexpected error processing audio input: {str(e)}")


def upload_audio_to_s3(audio_data: bytes, bucket_name: str, key: str) -> str:
    """
    Upload audio file to S3 and return the S3 URI
    
    Args:
        audio_data: Audio file data as bytes
        bucket_name: S3 bucket name
        key: S3 object key
        
    Returns:
        S3 URI of the uploaded file
        
    Raises:
        ClientError: If S3 operation fails (bucket access, upload failures)
        ValueError: If required parameters are missing or invalid
    """
    if not audio_data:
        raise ValueError("Audio data cannot be empty")
    if not bucket_name:
        raise ValueError("Bucket name cannot be empty")
    if not key:
        raise ValueError("S3 key cannot be empty")
    
    try:
        # Initialize S3 client with timeout configuration and hardcoded region
        s3_client = boto3.client(
            's3',
            region_name='us-east-1',
            config=boto3.session.Config(
                connect_timeout=60,
                read_timeout=60,
                retries={'max_attempts': 3}
            )
        )
        
        print(f"DEBUG: Starting S3 upload - bucket: {bucket_name}, key: {key}, size: {len(audio_data)} bytes")
        
        # Upload the audio file to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=audio_data,
            ContentType='audio/wav'
        )
        
        print(f"DEBUG: S3 upload completed successfully")
        
        # Return the S3 URI
        s3_uri = f"s3://{bucket_name}/{key}"
        return s3_uri
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        if error_code == 'NoSuchBucket':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"S3 bucket '{bucket_name}' does not exist"}},
                operation_name='PutObject'
            )
        elif error_code == 'AccessDenied':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Access denied to S3 bucket '{bucket_name}'. Check your AWS permissions."}},
                operation_name='PutObject'
            )
        else:
            # Re-raise the original error for other cases
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"S3 upload failed: {error_message}"}},
                operation_name='PutObject'
            )
    except Exception as e:
        raise Exception(f"Unexpected error during S3 upload: {str(e)}")


def start_transcription_job(s3_uri: str, job_name: str) -> str:
    """
    Start Amazon Transcribe job and return job name
    
    Args:
        s3_uri: S3 URI of the audio file
        job_name: Name for the transcription job
        
    Returns:
        Transcription job name
        
    Raises:
        ClientError: If Transcribe operation fails
        ValueError: If required parameters are missing or invalid
    """
    if not s3_uri:
        raise ValueError("S3 URI cannot be empty")
    if not job_name:
        raise ValueError("Job name cannot be empty")
    if not s3_uri.startswith('s3://'):
        raise ValueError("Invalid S3 URI format. Must start with 's3://'")
    
    try:
        # Initialize Transcribe client with hardcoded region
        transcribe_client = boto3.client('transcribe', region_name='us-east-1')
        
        # Start transcription job with English language setting
        response = transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            LanguageCode='en-US',
            MediaFormat='wav',
            Media={
                'MediaFileUri': s3_uri
            },
            OutputBucketName=s3_uri.split('/')[2]  # Extract bucket name from S3 URI
        )
        
        return response['TranscriptionJob']['TranscriptionJobName']
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        if error_code == 'ConflictException':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Transcription job '{job_name}' already exists"}},
                operation_name='StartTranscriptionJob'
            )
        elif error_code == 'AccessDeniedException':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': "Access denied to Amazon Transcribe. Check your AWS permissions."}},
                operation_name='StartTranscriptionJob'
            )
        elif error_code == 'BadRequestException':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Invalid request parameters: {error_message}"}},
                operation_name='StartTranscriptionJob'
            )
        else:
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Transcription job start failed: {error_message}"}},
                operation_name='StartTranscriptionJob'
            )
    except Exception as e:
        raise Exception(f"Unexpected error starting transcription job: {str(e)}")


def poll_transcription_status(job_name: str, progress_callback=None) -> dict:
    """
    Poll transcription job status until completion
    
    Args:
        job_name: Name of the transcription job
        progress_callback: Optional callback function to report progress updates
        
    Returns:
        Job status dictionary with keys: TranscriptionJobStatus, TranscriptionJobName, 
        TranscriptFileUri (if completed), FailureReason (if failed)
        
    Raises:
        ClientError: If Transcribe operation fails
        ValueError: If job name is missing
        TimeoutError: If job doesn't complete within timeout period (30 minutes)
    """
    if not job_name:
        raise ValueError("Job name cannot be empty")
    
    try:
        # Initialize Transcribe client with hardcoded region
        transcribe_client = boto3.client('transcribe', region_name='us-east-1')
        
        # Set timeout to 30 minutes (1800 seconds)
        timeout = 1800
        start_time = time.time()
        poll_interval = 10  # Poll every 10 seconds
        poll_count = 0
        
        while True:
            # Check if timeout exceeded
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout:
                raise TimeoutError(f"Transcription job '{job_name}' timed out after {timeout} seconds")
            
            # Get transcription job status
            response = transcribe_client.get_transcription_job(
                TranscriptionJobName=job_name
            )
            
            job_status = response['TranscriptionJob']['TranscriptionJobStatus']
            poll_count += 1
            
            # Call progress callback if provided
            if progress_callback:
                progress_info = {
                    'status': job_status,
                    'elapsed_time': elapsed_time,
                    'poll_count': poll_count,
                    'estimated_progress': min(elapsed_time / 300, 0.9)  # Estimate progress based on time, max 90%
                }
                progress_callback(progress_info)
            
            # Prepare return dictionary
            result = {
                'TranscriptionJobStatus': job_status,
                'TranscriptionJobName': job_name
            }
            
            if job_status == 'COMPLETED':
                result['TranscriptFileUri'] = response['TranscriptionJob']['Transcript']['TranscriptFileUri']
                if progress_callback:
                    progress_callback({'status': 'COMPLETED', 'estimated_progress': 1.0})
                return result
            elif job_status == 'FAILED':
                result['FailureReason'] = response['TranscriptionJob'].get('FailureReason', 'Unknown failure reason')
                return result
            elif job_status in ['IN_PROGRESS', 'QUEUED']:
                # Continue polling - wait before next check
                time.sleep(poll_interval)
                continue
            else:
                # Unknown status
                result['FailureReason'] = f"Unknown job status: {job_status}"
                return result
                
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        if error_code == 'BadRequestException':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Transcription job '{job_name}' not found or invalid"}},
                operation_name='GetTranscriptionJob'
            )
        elif error_code == 'AccessDeniedException':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': "Access denied to Amazon Transcribe. Check your AWS permissions."}},
                operation_name='GetTranscriptionJob'
            )
        else:
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Failed to get transcription job status: {error_message}"}},
                operation_name='GetTranscriptionJob'
            )
    except TimeoutError:
        # Re-raise timeout error as-is
        raise
    except Exception as e:
        raise Exception(f"Unexpected error polling transcription status: {str(e)}")


def get_transcription_result(job_name: str) -> str:
    """
    Retrieve transcription text from completed job
    
    Args:
        job_name: Name of the completed transcription job
        
    Returns:
        Transcription text
        
    Raises:
        ClientError: If Transcribe or S3 operations fail
        ValueError: If job name is missing or job is not completed
        Exception: For other unexpected errors
    """
    if not job_name:
        raise ValueError("Job name cannot be empty")
    
    try:
        # Initialize clients with hardcoded region
        transcribe_client = boto3.client('transcribe', region_name='us-east-1')
        s3_client = boto3.client('s3', region_name='us-east-1')
        
        # Get transcription job details
        response = transcribe_client.get_transcription_job(
            TranscriptionJobName=job_name
        )
        
        job_status = response['TranscriptionJob']['TranscriptionJobStatus']
        
        if job_status != 'COMPLETED':
            raise ValueError(f"Transcription job '{job_name}' is not completed. Current status: {job_status}")
        
        # Get the transcript file URI
        transcript_uri = response['TranscriptionJob']['Transcript']['TranscriptFileUri']
        print(f"Debug: Transcript URI: {transcript_uri}")
        
        # Parse S3 URI to get bucket and key with proper validation
        # URI format: https://s3.region.amazonaws.com/bucket-name/key
        # or https://bucket-name.s3.region.amazonaws.com/key
        # or s3://bucket-name/key
        if transcript_uri.startswith('https://'):
            # Parse HTTPS S3 URL with proper domain validation
            parts = transcript_uri.replace('https://', '').split('/')
            hostname = parts[0].lower()
            
            # Validate that this is actually an AWS S3 domain
            if hostname.startswith('s3.') and hostname.endswith('.amazonaws.com'):
                # Format: https://s3.region.amazonaws.com/bucket-name/key
                # Validate the hostname format more strictly
                hostname_parts = hostname.split('.')
                if len(hostname_parts) == 4 and hostname_parts[0] == 's3' and hostname_parts[2] == 'amazonaws' and hostname_parts[3] == 'com':
                    bucket_name = parts[1] if len(parts) > 1 else ''
                    key = '/'.join(parts[2:]) if len(parts) > 2 else ''
                else:
                    raise ValueError(f"Invalid S3 hostname format: {hostname}")
            elif hostname.endswith('.s3.amazonaws.com') or (hostname.count('.s3.') == 1 and hostname.endswith('.amazonaws.com')):
                # Format: https://bucket-name.s3.region.amazonaws.com/key
                # Validate the hostname format more strictly
                if '.s3.' in hostname and hostname.endswith('.amazonaws.com'):
                    s3_index = hostname.find('.s3.')
                    bucket_name = hostname[:s3_index]
                    # Validate bucket name doesn't contain suspicious characters
                    if not bucket_name or '.' in bucket_name[:-1] or bucket_name.startswith('-') or bucket_name.endswith('-'):
                        # Allow dots in bucket names but be more careful about validation
                        pass
                    key = '/'.join(parts[1:]) if len(parts) > 1 else ''
                else:
                    raise ValueError(f"Invalid S3 hostname format: {hostname}")
            else:
                raise ValueError(f"Invalid S3 hostname - not an AWS S3 domain: {hostname}")
        elif transcript_uri.startswith('s3://'):
            # Parse S3 URI
            uri_parts = transcript_uri.replace('s3://', '').split('/', 1)
            bucket_name = uri_parts[0]
            key = uri_parts[1] if len(uri_parts) > 1 else ''
            
            # Validate bucket name format
            if not bucket_name or len(bucket_name) < 3 or len(bucket_name) > 63:
                raise ValueError(f"Invalid S3 bucket name: {bucket_name}")
        else:
            raise ValueError(f"Invalid transcript URI format: {transcript_uri}")
        
        print(f"Debug: Parsed bucket: {bucket_name}, key: {key}")
        
        # Download transcript file from S3
        transcript_response = s3_client.get_object(Bucket=bucket_name, Key=key)
        transcript_json = transcript_response['Body'].read().decode('utf-8')
        
        # Parse JSON to extract transcript text
        transcript_data = json.loads(transcript_json)
        
        # Extract the transcript text from the results
        transcript_text = transcript_data['results']['transcripts'][0]['transcript']
        
        return transcript_text
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        if error_code == 'BadRequestException':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Transcription job '{job_name}' not found"}},
                operation_name='GetTranscriptionJob'
            )
        elif error_code == 'NoSuchKey':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Transcript file not found in S3"}},
                operation_name='GetObject'
            )
        elif error_code == 'AccessDenied':
            # Provide more specific guidance based on which operation failed
            operation = e.operation_name if hasattr(e, 'operation_name') else 'Unknown'
            if operation == 'GetObject':
                message = f"Access denied to S3 bucket '{bucket_name}'. Check your S3 permissions for GetObject on bucket and key: {key}"
            else:
                message = "Access denied. Check your AWS permissions for Transcribe and S3."
            
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': message}},
                operation_name=operation
            )
        else:
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Failed to retrieve transcription result: {error_message}"}},
                operation_name='GetTranscriptionJob'
            )
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse transcript JSON: {str(e)}")
    except KeyError as e:
        raise Exception(f"Unexpected transcript JSON structure. Missing key: {str(e)}")
    except Exception as e:
        raise Exception(f"Unexpected error retrieving transcription result: {str(e)}")


def convert_transcript_to_spec(transcript: str, model_id: str = None) -> Tuple[str, str]:
    """
    Use Bedrock Claude to convert transcript to Kiro spec format
    
    Args:
        transcript: Transcribed text
        model_id: Bedrock model ID to use (defaults to Claude 3.5 Sonnet v2)
        
    Returns:
        Tuple of (specification_content, project_name)
        
    Raises:
        ClientError: If Bedrock API operation fails
        ValueError: If transcript is empty or response is invalid
        Exception: For other unexpected errors
    """
    if model_id is None:
        model_id = os.environ.get("BEDROCK_MODEL_ID", "eu.anthropic.claude-haiku-4-5-20251001-v1:0")

    if not transcript or not transcript.strip():
        raise ValueError("Transcript cannot be empty")
    
    # Retry configuration
    max_retries = 3
    base_delay = 1  # Base delay in seconds
    max_delay = 30  # Maximum delay in seconds
    
    for attempt in range(max_retries + 1):
        try:
            # Initialize Bedrock Runtime client in the region that matches the model ID
            bedrock_client = boto3.client(
                'bedrock-runtime', region_name=resolve_bedrock_region(model_id)
            )
            
            # Create prompt template for converting transcript to Kiro spec format
            prompt_template = """You are an expert software requirements analyst. Your task is to convert the following spoken requirements transcript into a detailed Kiro specs-driven development format.

Please analyze the transcript and create:
1. A comprehensive requirements document in markdown format following Kiro specifications
2. A suitable project repository name (kebab-case format)

The requirements document should include:
- Clear introduction section summarizing the feature
- Hierarchical numbered list of requirements
- Each requirement should have a user story in format: "As a [role], I want [feature], so that [benefit]"
- Numbered acceptance criteria in EARS format (Easy Approach to Requirements Syntax)
- Use WHEN/THEN/IF/SHALL structure for acceptance criteria

TRANSCRIPT:
{transcript}

Please respond in the following JSON format:
{{
    "project_name": "project-name-in-kebab-case",
    "specification_content": "# Requirements Document\\n\\n## Introduction\\n\\n[content here]\\n\\n## Requirements\\n\\n### Requirement 1\\n\\n**User Story:** As a [role], I want [feature], so that [benefit]\\n\\n#### Acceptance Criteria\\n\\n1. WHEN [event] THEN [system] SHALL [response]\\n2. IF [condition] THEN [system] SHALL [response]\\n\\n[continue with more requirements as needed]"
}}

Ensure the project name is descriptive, uses kebab-case, and reflects the main purpose of the project described in the transcript."""

            # Format the prompt with the transcript
            formatted_prompt = prompt_template.format(transcript=transcript)
            
            # Prepare the request for Bedrock converse API
            request_body = {
                "modelId": model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": formatted_prompt}]
                    }
                ],
                "inferenceConfig": {
                    "maxTokens": 4000,
                    "temperature": 0.1
                }
            }
            
            print(f"DEBUG: Bedrock API call attempt {attempt + 1}/{max_retries + 1}")
            
            # Call Bedrock converse API
            response = bedrock_client.converse(**request_body)
            
            # Extract the response content
            if 'output' not in response or 'message' not in response['output']:
                raise ValueError("Invalid response structure from Bedrock API")
            
            message_content = response['output']['message']['content']
            if not message_content or len(message_content) == 0:
                raise ValueError("Empty response content from Bedrock API")
            
            # Get the text content from the response
            response_text = message_content[0]['text']
            print(f"DEBUG: Bedrock response text: {response_text[:200]}...")
            
            # Parse the JSON response to extract specification content and project name
            try:
                # Find JSON content in the response (handle cases where model adds extra text)
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                
                if json_start == -1 or json_end == 0:
                    raise ValueError("No JSON content found in Bedrock response")
                
                json_content = response_text[json_start:json_end]
                parsed_response = json.loads(json_content)
                
                # Validate required fields
                if 'project_name' not in parsed_response:
                    raise ValueError("Missing 'project_name' in Bedrock response")
                if 'specification_content' not in parsed_response:
                    raise ValueError("Missing 'specification_content' in Bedrock response")
                
                project_name = parsed_response['project_name'].strip()
                specification_content = parsed_response['specification_content'].strip()
                
                # Validate project name format (kebab-case)
                if not project_name or not all(c.islower() or c.isdigit() or c == '-' for c in project_name):
                    raise ValueError(f"Invalid project name format: '{project_name}'. Must be kebab-case.")
                
                # Validate specification content is not empty
                if not specification_content:
                    raise ValueError("Specification content cannot be empty")
                
                print(f"DEBUG: Successfully parsed Bedrock response on attempt {attempt + 1}")
                return specification_content, project_name
                
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse JSON response from Bedrock: {str(e)}")
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            # Check if this is a retryable error
            retryable_errors = ['ThrottlingException', 'ServiceUnavailableException', 'InternalServerException']
            
            if error_code in retryable_errors and attempt < max_retries:
                # Calculate exponential backoff delay
                delay = min(base_delay * (2 ** attempt), max_delay)
                print(f"DEBUG: Retryable error {error_code} on attempt {attempt + 1}. Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            
            # Non-retryable errors or max retries exceeded
            if error_code == 'AccessDeniedException':
                raise ClientError(
                    error_response={'Error': {'Code': error_code, 'Message': "Access denied to Amazon Bedrock. Check your AWS permissions and model access."}},
                    operation_name='Converse'
                )
            elif error_code == 'ThrottlingException':
                raise ClientError(
                    error_response={'Error': {'Code': error_code, 'Message': "Bedrock API rate limit exceeded. Please try again later."}},
                    operation_name='Converse'
                )
            elif error_code == 'ValidationException':
                raise ClientError(
                    error_response={'Error': {'Code': error_code, 'Message': f"Invalid request parameters for Bedrock API: {error_message}"}},
                    operation_name='Converse'
                )
            elif error_code == 'ModelNotReadyException':
                raise ClientError(
                    error_response={'Error': {'Code': error_code, 'Message': "Claude 3.5 Sonnet model is not ready. Please try again later."}},
                    operation_name='Converse'
                )
            elif error_code == 'ServiceQuotaExceededException':
                raise ClientError(
                    error_response={'Error': {'Code': error_code, 'Message': "Bedrock service quota exceeded. Please check your usage limits."}},
                    operation_name='Converse'
                )
            else:
                raise ClientError(
                    error_response={'Error': {'Code': error_code, 'Message': f"Bedrock API call failed: {error_message}"}},
                    operation_name='Converse'
                )
        
        except ValueError as e:
            # For JSON parsing errors, retry if we haven't exceeded max attempts
            if "No JSON content found" in str(e) and attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                print(f"DEBUG: JSON parsing error on attempt {attempt + 1}. Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                # Re-raise ValueError if not retryable or max retries exceeded
                raise
        
        except Exception as e:
            # For unexpected errors, retry if we haven't exceeded max attempts
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                print(f"DEBUG: Unexpected error on attempt {attempt + 1}: {str(e)}. Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                raise Exception(f"Unexpected error calling Bedrock API after {max_retries + 1} attempts: {str(e)}")
    
    # This should never be reached, but just in case
    raise Exception(f"Failed to get valid response from Bedrock API after {max_retries + 1} attempts")


def generate_tasks_from_spec(spec_content: str, model_id: str = None) -> str:
    """Generate tasks.md from requirements spec using Bedrock."""
    if model_id is None:
        model_id = os.environ.get("BEDROCK_MODEL_ID", "eu.anthropic.claude-haiku-4-5-20251001-v1:0")

    if not spec_content or not spec_content.strip():
        raise ValueError("Specification content cannot be empty")

    bedrock_client = boto3.client(
        'bedrock-runtime', region_name=resolve_bedrock_region(model_id)
    )

    prompt = f"""You are an expert software engineer. Given the following requirements specification, generate a detailed tasks.md file that an AI coding agent can follow to implement the project and satisfy all acceptance criteria.

For each requirement, create actionable implementation tasks with:
- Clear task title
- Step-by-step subtasks
- Files to create or modify
- Exit criteria that map back to the acceptance criteria

Use markdown with checkboxes (- [ ]) so progress can be tracked.

REQUIREMENTS:
{spec_content}

Respond with ONLY the markdown content for tasks.md, no JSON wrapping."""

    response = bedrock_client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 4000, "temperature": 0.1}
    )

    return response['output']['message']['content'][0]['text'].strip()


def upload_requirements_to_s3(bucket_name: str, project_name: str, requirements_content: str) -> str:
    """
    Upload requirements.md file to S3 following project/name/requirement structure
    
    Args:
        bucket_name: S3 bucket name
        project_name: Name of the project (used in S3 key path)
        requirements_content: Content of the requirements.md file
        
    Returns:
        S3 URI of the uploaded requirements file
        
    Raises:
        ClientError: If S3 operation fails
        ValueError: If required parameters are missing or invalid
    """
    if not bucket_name:
        raise ValueError("Bucket name cannot be empty")
    if not project_name:
        raise ValueError("Project name cannot be empty")
    if not requirements_content:
        raise ValueError("Requirements content cannot be empty")
    
    try:
        # Initialize S3 client with timeout configuration and hardcoded region
        s3_client = boto3.client(
            's3',
            region_name='us-east-1',
            config=boto3.session.Config(
                connect_timeout=60,
                read_timeout=60,
                retries={'max_attempts': 3}
            )
        )
        
        # Create S3 key following project/name/requirement structure
        s3_key = f"projects/{project_name}/requirements.md"
        
        print(f"DEBUG: Starting S3 requirements upload - bucket: {bucket_name}, key: {s3_key}")
        
        # Upload the requirements file to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=requirements_content.encode('utf-8'),
            ContentType='text/markdown'
        )
        
        print(f"DEBUG: S3 requirements upload completed successfully")
        
        # Return the S3 URI
        s3_uri = f"s3://{bucket_name}/{s3_key}"
        return s3_uri
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        if error_code == 'NoSuchBucket':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"S3 bucket '{bucket_name}' does not exist"}},
                operation_name='PutObject'
            )
        elif error_code == 'AccessDenied':
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"Access denied to S3 bucket '{bucket_name}'. Check your AWS permissions."}},
                operation_name='PutObject'
            )
        else:
            raise ClientError(
                error_response={'Error': {'Code': error_code, 'Message': f"S3 requirements upload failed: {error_message}"}},
                operation_name='PutObject'
            )
    except Exception as e:
        raise Exception(f"Unexpected error during S3 requirements upload: {str(e)}")


def create_project_folder(project_name: str, spec_content: str, tasks_content: str = None) -> bool:
    """
    Create local folder under 'projects' directory and save requirements.md file
    
    Args:
        project_name: Name of the project folder (should be in kebab-case format)
        spec_content: Specification content to save as requirements.md
        
    Returns:
        True if successful
        
    Raises:
        ValueError: If project name or spec content is invalid
        OSError: If folder creation or file writing fails due to permissions or disk space
        Exception: For other unexpected file system errors
    """
    if not project_name or not project_name.strip():
        raise ValueError("Project name cannot be empty")
    
    if not spec_content or not spec_content.strip():
        raise ValueError("Specification content cannot be empty")
    
    # Validate project name format (should be kebab-case)
    project_name = project_name.strip()
    
    # Prevent directory traversal attacks first
    if '..' in project_name or '/' in project_name or '\\' in project_name:
        raise ValueError(f"Invalid project name: '{project_name}'. Cannot contain path separators or parent directory references.")
    
    # Then check kebab-case format
    if not all(c.islower() or c.isdigit() or c == '-' or c == '_' for c in project_name):
        raise ValueError(f"Invalid project name format: '{project_name}'. Must be kebab-case (lowercase letters, numbers, hyphens, underscores only).")
    
    try:
        # Get current working directory and create projects directory path
        current_dir = os.getcwd()
        projects_dir = os.path.join(current_dir, 'projects')
        
        # Create the "projects" directory if it doesn't exist
        if not os.path.exists(projects_dir):
            os.makedirs(projects_dir, exist_ok=True)
        elif not os.path.isdir(projects_dir):
            raise OSError(f"A file named 'projects' already exists in the current directory and is not a folder")
        
        # Create the project path under the projects directory
        project_path = os.path.join(projects_dir, project_name)
        
        # Check if project folder already exists
        if os.path.exists(project_path):
            if not os.path.isdir(project_path):
                raise OSError(f"A file with the name '{project_name}' already exists in the projects directory")
            # If directory exists, we'll continue and overwrite the requirements.md file
        else:
            # Create the project directory
            os.makedirs(project_path, exist_ok=True)
        
        # Create the requirements.md file path
        requirements_file_path = os.path.join(project_path, 'requirements.md')
        
        # Write the specification content to requirements.md
        with open(requirements_file_path, 'w', encoding='utf-8') as f:
            f.write(spec_content)
        
        # Verify the file was created and has content
        if not os.path.exists(requirements_file_path):
            raise OSError(f"Failed to create requirements.md file at {requirements_file_path}")
        
        # Check file size to ensure content was written
        file_size = os.path.getsize(requirements_file_path)
        if file_size == 0:
            raise OSError(f"Requirements.md file was created but is empty at {requirements_file_path}")
        
        # Write tasks.md if provided
        if tasks_content and tasks_content.strip():
            tasks_file_path = os.path.join(project_path, 'tasks.md')
            with open(tasks_file_path, 'w', encoding='utf-8') as f:
                f.write(tasks_content)
        
        return True
        
    except PermissionError as e:
        raise OSError(f"Permission denied: Cannot create projects directory or project folder '{project_name}' or write requirements.md file. Check your file system permissions. Details: {str(e)}")
    except FileNotFoundError as e:
        raise OSError(f"Path not found: Cannot create projects directory or project folder '{project_name}'. The current directory may not exist. Details: {str(e)}")
    except OSError as e:
        # Re-raise OSError with more context
        if "No space left on device" in str(e):
            raise OSError(f"Insufficient disk space to create projects directory and project folder '{project_name}' with requirements.md file")
        elif "File name too long" in str(e):
            raise OSError(f"Project name '{project_name}' is too long for the file system")
        else:
            raise OSError(f"File system error creating project folder '{project_name}' under projects directory: {str(e)}")
    except UnicodeEncodeError as e:
        raise Exception(f"Failed to write specification content due to encoding error: {str(e)}")
    except Exception as e:
        raise Exception(f"Unexpected error creating project folder '{project_name}' under projects directory: {str(e)}")


def convert_transcript_to_github_issue(transcript: str, model_id: str = None) -> Tuple[str, str]:
    """
    Use Bedrock Claude to convert a transcript directly into a GitHub issue
    (title + body). This skips the full requirements/design/tasks pipeline and
    produces a single actionable task suitable for tracking on GitHub.

    Args:
        transcript: Transcribed text from the audio input
        model_id: Bedrock model ID to use (defaults to env BEDROCK_MODEL_ID)

    Returns:
        Tuple of (title, body) for the GitHub issue.

    Raises:
        ValueError: If transcript is empty or the model response is malformed.
        ClientError: If the Bedrock API call fails.
    """
    if model_id is None:
        model_id = os.environ.get(
            "BEDROCK_MODEL_ID",
            "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        )

    if not transcript or not transcript.strip():
        raise ValueError("Transcript cannot be empty")

    bedrock_client = boto3.client(
        'bedrock-runtime', region_name=resolve_bedrock_region(model_id)
    )

    prompt = f"""You are turning a spoken product request into a single actionable GitHub issue.

Skip any formal requirements or design documents. Produce a concise, implementation-ready task.

The issue body (markdown) should contain:
- A short "## Summary" paragraph describing the goal.
- A "## Acceptance Criteria" section with a bulleted checklist (- [ ] items).
- An optional "## Notes" section only if the transcript mentions constraints, dependencies, or out-of-scope items.

Keep the title under 80 characters, imperative mood, no trailing punctuation.

Respond with ONLY valid JSON in this exact shape:
{{
    "title": "Short imperative title",
    "body": "Markdown body here"
}}

TRANSCRIPT:
{transcript}
"""

    response = bedrock_client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 2000, "temperature": 0.1},
    )

    response_text = response['output']['message']['content'][0]['text']

    # Tolerate models that wrap JSON in prose.
    json_start = response_text.find('{')
    json_end = response_text.rfind('}') + 1
    if json_start == -1 or json_end == 0:
        raise ValueError("No JSON content found in Bedrock response for GitHub issue")

    parsed = json.loads(response_text[json_start:json_end])

    title = (parsed.get('title') or '').strip()
    body = (parsed.get('body') or '').strip()

    if not title:
        raise ValueError("Bedrock response missing 'title' for GitHub issue")
    if not body:
        raise ValueError("Bedrock response missing 'body' for GitHub issue")

    return title, body


def create_github_issue(
    repo: str,
    title: str,
    body: str,
    token: str,
    labels: list = None,
) -> dict:
    """
    Create a GitHub issue in the given repository using the REST API.

    Args:
        repo: Repository in "owner/repo" format.
        title: Issue title.
        body: Issue body (markdown).
        token: GitHub personal access token with issue write permission.
        labels: Optional list of label names to apply.

    Returns:
        Dict with keys: number, html_url, api_url.

    Raises:
        ValueError: If required parameters are missing or malformed.
        RuntimeError: If the GitHub API returns a non-success response.
    """
    if not repo or '/' not in repo:
        raise ValueError("GitHub repo must be in 'owner/repo' format")
    if not title or not title.strip():
        raise ValueError("Issue title cannot be empty")
    if not body or not body.strip():
        raise ValueError("Issue body cannot be empty")
    if not token:
        raise ValueError("GitHub token is required")

    url = f"https://api.github.com/repos/{repo}/issues"
    payload = {"title": title.strip(), "body": body.strip()}
    if labels:
        payload["labels"] = labels

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "maersk-kiro-demo",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            issue = json.loads(response_body)
            return {
                "number": issue.get("number"),
                "html_url": issue.get("html_url"),
                "api_url": issue.get("url"),
            }
    except urllib.error.HTTPError as e:
        # Surface the GitHub error details to make debugging easier.
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            error_body = ""
        raise RuntimeError(
            f"GitHub API error {e.code} {e.reason} while creating issue in '{repo}': {error_body}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error calling GitHub API: {e.reason}") from e


# --------------------------------------------------------------------------- #
# Local transcription engine: Parakeet MLX (Apple Silicon)
# --------------------------------------------------------------------------- #

PARAKEET_DEFAULT_MODEL = os.environ.get(
    "PARAKEET_MODEL_ID", "mlx-community/parakeet-tdt-0.6b-v2"
)


def is_parakeet_available() -> bool:
    """
    Return True when the Parakeet MLX engine can be used on this host.

    Requires:
    - `parakeet_mlx` importable (install via `uv sync --extra local-transcribe`).
    - `ffmpeg` available on PATH for audio preprocessing.
    """
    try:
        import importlib.util
        if importlib.util.find_spec("parakeet_mlx") is None:
            return False
    except Exception:
        return False

    import shutil
    return shutil.which("ffmpeg") is not None


def _load_parakeet_model(model_id: str):
    """Lazily load and cache the Parakeet model on first use."""
    import functools

    @functools.lru_cache(maxsize=2)
    def _cached(mid: str):
        from parakeet_mlx import from_pretrained
        return from_pretrained(mid)

    # Stash the cache on the module so repeated calls reuse it across reruns.
    global _PARAKEET_CACHE
    try:
        _PARAKEET_CACHE
    except NameError:
        _PARAKEET_CACHE = _cached
    return _PARAKEET_CACHE(model_id)


def transcribe_with_parakeet(
    audio_bytes: bytes,
    model_id: str = None,
    chunk_duration: float = 120.0,
    overlap_duration: float = 15.0,
) -> str:
    """
    Transcribe audio bytes locally using Parakeet MLX.

    The input may be in any format ffmpeg can read (WAV, WebM/Opus from the
    browser recorder, MP3, etc.). It is normalized to 16 kHz mono PCM WAV
    before transcription, matching the reference example's pipeline.

    Args:
        audio_bytes: Raw audio bytes from either the file uploader or
                     st.audio_input.
        model_id: Parakeet model ID on Hugging Face. Defaults to the
                  TDT 0.6B v2 community checkpoint.
        chunk_duration: Seconds per chunk for long-form transcription.
        overlap_duration: Overlap between chunks to preserve continuity.

    Returns:
        The transcript as plain text (whitespace-stripped).

    Raises:
        ValueError: If audio_bytes is empty.
        RuntimeError: If parakeet_mlx / ffmpeg are unavailable or fail.
    """
    if not audio_bytes:
        raise ValueError("Audio data cannot be empty")

    if not is_parakeet_available():
        raise RuntimeError(
            "Parakeet MLX is not available. Install with "
            "`uv sync --extra local-transcribe` and ensure `ffmpeg` is on PATH."
        )

    import shutil
    import subprocess
    import tempfile

    target_model = model_id or PARAKEET_DEFAULT_MODEL

    src_file = None
    wav_file = None
    try:
        # Persist the incoming bytes so ffmpeg can read them from disk.
        src_file = tempfile.NamedTemporaryFile(suffix=".audio", delete=False)
        src_file.write(audio_bytes)
        src_file.close()

        wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wav_file.close()

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-i", src_file.name,
                    "-vn",
                    "-acodec", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    "-y",
                    wav_file.name,
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"ffmpeg failed to prepare audio for Parakeet: {stderr.strip()}"
            ) from e

        model = _load_parakeet_model(target_model)
        result = model.transcribe(
            wav_file.name,
            chunk_duration=chunk_duration,
            overlap_duration=overlap_duration,
        )
        return (result.text or "").strip()
    finally:
        for f in (src_file, wav_file):
            if f is None:
                continue
            try:
                path = f.name
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass
