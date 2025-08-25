"""
Audio Transcription App - Main Streamlit Application

This application captures audio input from a user's browser microphone,
transcribes it using Amazon Transcribe, and converts the transcript into
a Kiro specification format using Amazon Bedrock Claude 3.7.
"""

import streamlit as st
from utils import (
    upload_audio_to_s3,
    start_transcription_job,
    poll_transcription_status,
    get_transcription_result,
    convert_transcript_to_spec,
    create_project_folder,
    generate_unique_filename,
    process_audio_input
)
import os


def initialize_session_state():
    """Initialize session state variables for tracking processing status and input method"""
    if 'processing_status' not in st.session_state:
        st.session_state.processing_status = 'idle'  # idle, uploading, transcribing, generating, complete
    if 'transcription_text' not in st.session_state:
        st.session_state.transcription_text = None
    if 'project_name' not in st.session_state:
        st.session_state.project_name = None
    if 'error_message' not in st.session_state:
        st.session_state.error_message = None
    if 'transcription_job_name' not in st.session_state:
        st.session_state.transcription_job_name = None
    if 'transcription_progress' not in st.session_state:
        st.session_state.transcription_progress = None
    if 'input_method' not in st.session_state:
        st.session_state.input_method = None  # 'microphone' or 'upload'
    if 'selected_audio_data' not in st.session_state:
        st.session_state.selected_audio_data = None


def reset_session_state():
    """Reset session state for a new recording"""
    st.session_state.processing_status = 'idle'
    st.session_state.transcription_text = None
    st.session_state.project_name = None
    st.session_state.error_message = None
    st.session_state.transcription_job_name = None
    st.session_state.transcription_progress = None
    st.session_state.input_method = None
    st.session_state.selected_audio_data = None


def main():
    """Main Streamlit application"""
    # Initialize session state
    initialize_session_state()
    
    # Page configuration and header
    st.set_page_config(
        page_title="Audio Transcription to Kiro Spec",
        page_icon="🎤",
        layout="centered"
    )
    
    # Main header with proper spacing
    st.title("🎤 Audio Transcription to Kiro Spec")
    st.markdown("---")
    
    # Description section
    st.markdown("""
    ### How it works:
    1. **Record** your project requirements using the microphone
    2. **Submit** to transcribe and generate a Kiro specification
    3. **Download** your structured requirements document
    """)
    
    st.markdown("---")
    
    # Audio input section with dual options
    st.subheader("🎤 Provide Your Requirements")
    st.write("Choose one of the following methods to provide your project requirements:")
    
    # Create tabs for input method selection
    tab1, tab2 = st.tabs(["🎙️ Record Audio", "📁 Upload File"])
    
    # Initialize variables for audio data
    recorded_audio = None
    uploaded_file = None
    current_audio_data = None
    
    with tab1:
        st.write("Click the microphone button below to start recording your project requirements.")
        
        # Audio input widget with proper labeling for microphone recording
        recorded_audio = st.audio_input(
            "Record your requirements",
            help="Click to start recording. Speak clearly about your project requirements."
        )
        
        # Handle microphone input method switching
        if recorded_audio is not None:
            if st.session_state.input_method != 'microphone':
                # Clear previous selections when switching methods
                st.session_state.input_method = 'microphone'
                st.session_state.selected_audio_data = recorded_audio
            current_audio_data = recorded_audio
            
            # Show recording info
            st.success("✅ Audio recorded successfully!")
    
    with tab2:
        st.write("Upload a .wav audio file containing your project requirements.")
        
        # File upload widget that accepts only .wav files
        uploaded_file = st.file_uploader(
            "Upload .wav file",
            type=['wav'],
            help="Select a .wav audio file from your computer. Only .wav format is supported."
        )
        
        # Handle file upload input method switching
        if uploaded_file is not None:
            if st.session_state.input_method != 'upload':
                # Clear previous selections when switching methods
                st.session_state.input_method = 'upload'
                st.session_state.selected_audio_data = uploaded_file
            current_audio_data = uploaded_file
            
            # Show upload info
            st.success("✅ File uploaded successfully!")
    
    # Determine which audio data to use (either microphone recording or file upload, not both)
    audio_data = None
    if st.session_state.input_method == 'microphone' and recorded_audio is not None:
        audio_data = recorded_audio
    elif st.session_state.input_method == 'upload' and uploaded_file is not None:
        audio_data = uploaded_file
    
    # Add some spacing
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Submit button section
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        # Submit button (disabled when no audio is provided through either method or currently processing)
        is_processing = st.session_state.processing_status != 'idle'
        has_audio = audio_data is not None
        
        # Dynamic button text based on input method
        if st.session_state.input_method == 'microphone':
            button_text = "🚀 Process Recording"
        elif st.session_state.input_method == 'upload':
            button_text = "🚀 Process Upload"
        else:
            button_text = "🚀 Process Audio"
        
        submit_button = st.button(
            button_text,
            disabled=(not has_audio or is_processing),
            use_container_width=True,
            type="primary",
            help="Process your audio input to generate Kiro specification" if has_audio else "Please provide audio input first"
        )
        
        # Show status message when no audio is provided
        if not has_audio and not is_processing:
            st.caption("⚠️ Please record audio or upload a .wav file to continue")
    
    # Reset button for new recording
    if st.session_state.processing_status in ['complete', 'error']:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🔄 Start New Recording", use_container_width=True):
                reset_session_state()
                st.rerun()
    
    # Processing status display with enhanced loading states
    if st.session_state.processing_status != 'idle':
        st.markdown("---")
        st.subheader("📊 Processing Status")
        
        # Status indicators based on current processing stage with spinners
        if st.session_state.processing_status == 'uploading':
            with st.spinner("Uploading audio to cloud storage..."):
                st.info("⏳ **Step 1/3:** Uploading your audio file to secure cloud storage")
                # Progress bar for upload step
                progress_bar = st.progress(0.33)
                
                # Detailed upload status
                st.write("📤 Preparing audio data and establishing secure connection...")
                st.write("🔐 Encrypting audio file for secure transmission...")
                st.write("☁️ Uploading to Amazon S3...")
                
                # Show technical details
                with st.expander("🔧 Upload Details", expanded=False):
                    st.write("**Process:**")
                    st.write("• Converting audio to WAV format")
                    st.write("• Generating unique filename with timestamp")
                    st.write("• Establishing secure connection to S3")
                    st.write("• Uploading with encryption in transit")
                    st.write("• Verifying upload completion")
        elif st.session_state.processing_status == 'transcribing':
            with st.spinner("Transcribing your audio..."):
                st.info("🎯 **Step 2/3:** Converting speech to text using AI transcription")
                
                # Show detailed transcription progress if available
                if st.session_state.transcription_progress:
                    progress_info = st.session_state.transcription_progress
                    progress_value = progress_info.get('estimated_progress', 0.66)
                    elapsed_time = progress_info.get('elapsed_time', 0)
                    status = progress_info.get('status', 'IN_PROGRESS')
                    poll_count = progress_info.get('poll_count', 0)
                    
                    # Progress bar with estimated completion
                    progress_bar = st.progress(progress_value)
                    
                    # Detailed status information
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"🔊 Status: **{status}**")
                        st.write(f"⏱️ Elapsed: **{int(elapsed_time)}s**")
                    with col2:
                        st.write(f"🔄 Checks: **{poll_count}**")
                        if status == 'IN_PROGRESS':
                            st.write("🎵 Processing audio...")
                        elif status == 'QUEUED':
                            st.write("⏳ Waiting in queue...")
                else:
                    # Default progress display
                    progress_bar = st.progress(0.66)
                    st.write("🔊 Analyzing audio patterns and generating transcript...")
                    st.write("⏱️ This may take a few minutes depending on audio length")
                
                # Show transcription job name if available
                if st.session_state.transcription_job_name:
                    with st.expander("🔧 Technical Details", expanded=False):
                        st.code(f"Job Name: {st.session_state.transcription_job_name}")
                        st.write("Amazon Transcribe is processing your audio file...")
                        st.write("The system polls every 10 seconds for status updates.")
                        st.write("Transcription results will be displayed once processing completes.")
        elif st.session_state.processing_status == 'generating':
            with st.spinner("Generating Kiro specification..."):
                st.info("✨ **Step 3/3:** Creating structured requirements document")
                # Progress bar for generation step
                progress_bar = st.progress(1.0)
                
                # Detailed generation status
                st.write("🤖 **Claude 3.5 Sonnet** is analyzing your requirements...")
                st.write("📝 Generating project name and detailed specifications...")
                st.write("🏗️ Structuring requirements in Kiro format...")
                
                # Show what the AI is doing
                with st.expander("🧠 AI Processing Details", expanded=False):
                    st.write("**Current Tasks:**")
                    st.write("• Analyzing transcript for key requirements")
                    st.write("• Identifying user stories and acceptance criteria")
                    st.write("• Generating appropriate project name")
                    st.write("• Formatting in EARS (Easy Approach to Requirements Syntax)")
                    st.write("• Creating hierarchical requirement structure")
                    
                    st.write("**Model:** Amazon Bedrock Claude 3.5 Sonnet")
                    st.write("**Expected Output:** Structured requirements.md file")
        elif st.session_state.processing_status == 'complete':
            st.success("✅ Processing complete!")
            # Show completed progress
            st.progress(1.0)
        elif st.session_state.processing_status == 'error':
            st.error(f"❌ Error: {st.session_state.error_message}")
            # Show error state in progress
            st.progress(0.0)
    
    # Display transcription results if available (before spec generation)
    if st.session_state.transcription_text and st.session_state.processing_status in ['generating', 'complete']:
        st.markdown("---")
        st.subheader("📝 Transcription Results")
        with st.expander("View Transcribed Text", expanded=True):
            # Format transcription for better readability
            formatted_text = st.session_state.transcription_text.strip()
            
            # Add basic formatting improvements
            # Split into sentences for better readability
            sentences = formatted_text.replace('. ', '.\n\n').replace('? ', '?\n\n').replace('! ', '!\n\n')
            
            st.markdown("**Transcribed Content:**")
            st.text_area(
                "Your spoken requirements have been converted to text:",
                value=sentences,
                height=200,
                disabled=True,
                help="This is the text extracted from your audio recording. Review it before proceeding to specification generation."
            )
            
            # Show transcription metadata
            word_count = len(formatted_text.split())
            char_count = len(formatted_text)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Word Count", word_count)
            with col2:
                st.metric("Character Count", char_count)
            with col3:
                estimated_duration = max(1, word_count // 150)  # Rough estimate: 150 words per minute
                st.metric("Est. Duration", f"{estimated_duration} min")
        
        # Show next step information
        if st.session_state.processing_status == 'generating':
            st.info("✨ Now generating your Kiro specification from this transcription...")
        elif st.session_state.processing_status == 'complete':
            st.success("✅ Specification generated successfully from this transcription!")
    
    # Display success message and project info
    if st.session_state.processing_status == 'complete' and st.session_state.project_name:
        st.markdown("---")
        st.subheader("🎉 Success!")
        
        # Enhanced success messaging with detailed information
        st.success("✅ **Project created successfully!**")
        
        # Project details in an attractive info box
        st.info(f"""
        **📁 Project Name:** `{st.session_state.project_name}`
        
        **📄 Files Created:**
        - `{st.session_state.project_name}/requirements.md` - Your structured requirements document
        
        **📍 Location:** Current directory (`{os.getcwd()}`)
        """)
        
        # Action buttons for next steps
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col2:
            if st.button("🔄 Create Another Project", help="Start over with a new recording", use_container_width=True):
                reset_session_state()
                st.rerun()
        
        # Additional helpful information
        with st.expander("📋 Next Steps", expanded=False):
            st.markdown(f"""
            **What's been created:**
            1. A new project folder named `{st.session_state.project_name}`
            2. A `requirements.md` file with your structured requirements in Kiro format
            
            **Recommended next steps:**
            1. Review the generated requirements document
            2. Use Kiro to create a design document from these requirements
            3. Generate implementation tasks and start coding
            4. Iterate and refine as needed
            
            **File Location:**
            ```
            {os.getcwd()}/
            └── {st.session_state.project_name}/
                └── requirements.md
            ```
            """)
        
        # Show a preview of the generated content
        if st.button("👀 Preview Generated Requirements", help="View the content that was generated"):
            try:
                requirements_path = os.path.join(os.getcwd(), st.session_state.project_name, "requirements.md")
                if os.path.exists(requirements_path):
                    with open(requirements_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    st.markdown("### 📄 Generated Requirements Preview")
                    with st.expander("View requirements.md content", expanded=True):
                        st.markdown(content)
                else:
                    st.error("Requirements file not found. There may have been an issue with file creation.")
            except Exception as e:
                st.error(f"Error reading requirements file: {str(e)}")
    
    # Processing workflow - orchestrate the complete audio-to-spec pipeline
    if submit_button and audio_data is not None:
        try:
            # Get required environment variables
            bucket_name = os.getenv('S3_BUCKET_NAME')
            if not bucket_name:
                st.session_state.error_message = "S3_BUCKET_NAME environment variable is not set"
                st.session_state.processing_status = 'error'
                st.rerun()
                return
            
            # Step 1: Upload audio to S3 with loading state
            st.session_state.processing_status = 'uploading'
            
            # Show upload progress immediately
            with st.spinner("Uploading audio to cloud storage..."):
                st.info("⏳ **Step 1/3:** Uploading your audio file to secure cloud storage")
                
                # Generate unique filename and upload to S3
                filename = generate_unique_filename()
                
                # Handle both input methods - get audio bytes using utility function
                if st.session_state.input_method == 'microphone':
                    audio_bytes = audio_data.getvalue()
                    st.write(f"🎙️ Processing microphone recording")
                elif st.session_state.input_method == 'upload':
                    audio_bytes = audio_data.getvalue()
                    st.write(f"📁 Processing uploaded file")
                else:
                    # Fallback for direct audio_data
                    audio_bytes = audio_data.getvalue()
                    st.write(f"🎵 Processing audio input")
                
                s3_uri = upload_audio_to_s3(audio_bytes, bucket_name, filename)
                st.write(f"✅ Upload successful")
            
            # Step 2: Start transcription job with enhanced progress tracking
            st.session_state.processing_status = 'transcribing'
            
            with st.spinner("Starting transcription job..."):
                st.info("🎯 **Step 2/3:** Converting speech to text using AI transcription")
                
                # Create unique job name based on filename
                job_name = f"transcription_{filename.replace('.wav', '').replace('_', '-')}"
                transcription_job_name = start_transcription_job(s3_uri, job_name)
                st.session_state.transcription_job_name = transcription_job_name
            
            # Poll for transcription completion with progress tracking
            with st.spinner("Transcribing your audio..."):
                # Define progress callback for transcription polling
                def update_transcription_progress(progress_info):
                    st.session_state.transcription_progress = progress_info
                
                job_status = poll_transcription_status(transcription_job_name, update_transcription_progress)
            
            if job_status['TranscriptionJobStatus'] != 'COMPLETED':
                error_reason = job_status.get('FailureReason', 'Unknown transcription failure')
                st.session_state.error_message = f"Transcription failed: {error_reason}"
                st.session_state.processing_status = 'error'
                st.rerun()
                return
            
            # Get transcription result
            transcription_text = get_transcription_result(transcription_job_name)
            st.session_state.transcription_text = transcription_text
            
            # Step 3: Generate specification using Bedrock with loading state
            st.session_state.processing_status = 'generating'
            
            with st.spinner("Generating Kiro specification..."):
                st.info("✨ **Step 3/3:** Creating structured requirements document")
                
                spec_content, project_name = convert_transcript_to_spec(transcription_text)
                st.session_state.project_name = project_name
                
                # Step 4: Create local project folder and save requirements.md
                create_project_folder(project_name, spec_content)
            
            # Mark as complete
            st.session_state.processing_status = 'complete'
            st.success("✅ Processing complete!")
            st.rerun()
            
        except Exception as e:
            # Handle any errors in the workflow
            import traceback
            error_details = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            st.session_state.error_message = error_details
            st.session_state.processing_status = 'error'
            st.rerun()
    
    # Footer with spacing
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown(
        "<div style='text-align: center; color: #666;'>"
        "Powered by Amazon Transcribe & Bedrock Claude 3.7"
        "</div>",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()