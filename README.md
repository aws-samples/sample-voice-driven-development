# Voice-Driven Development

Convert spoken requirements into structured Kiro specifications using AI transcription and LLM processing.

This Streamlit application captures audio input (microphone or file upload), transcribes it using Amazon Transcribe, and generates structured requirements documents using Amazon Bedrock Claude 3.5 Sonnet.

## Features

- 🎤 Browser microphone recording or .wav file upload
- 🔊 AI transcription via Amazon Transcribe
- ✨ Structured spec generation using Claude 3.5 Sonnet
- 📝 Automatic project creation with requirements.md files

## Prerequisites

- [uv package manager](https://docs.astral.sh/uv/getting-started/installation/) installed
- AWS account with access to S3, Transcribe, and Bedrock services
- Bedrock model access for Claude 3.5 Sonnet or any other model (request via AWS Console)
- S3 bucket for audio storage

## Quick Start

### Option 1: Direct Launch (Recommended)

```bash
git clone https://github.com/aws-samples/sample-voice-driven-development
cd sample-voice-driven-development
uv sync
export S3_BUCKET_NAME=your-s3-bucket-name
uv run streamlit run streamlit_app.py
```

### Option 2: Docker

Using AWS credentials volume mount:

```bash
docker build -t voice-driven-dev .
docker run -p 8501:8501 \
  -e S3_BUCKET_NAME=your_bucket_name \
  -v ~/.aws:/home/appuser/.aws:ro \
  -v $(pwd)/projects:/app/projects \
  voice-driven-dev
```

Or with environment variables:

```bash
docker run -p 8501:8501 \
  -e AWS_ACCESS_KEY_ID=your_access_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret_key \
  -e S3_BUCKET_NAME=your_bucket_name \
  -v $(pwd)/projects:/app/projects \
  voice-driven-dev
```

Access the app at `http://localhost:8501`

## Usage

1. Record audio or upload `.wav` file with your requirements
2. Click process to transcribe and generate specifications
3. Download the generated requirements.md file
4. Find your project in the `projects/` directory or download from the web UI.

## AWS Permissions

Your credentials need access to:

- S3: PutObject, GetObject on your bucket
- Transcribe: StartTranscriptionJob, GetTranscriptionJob
- Bedrock: InvokeModel for Claude 3.5 Sonnet