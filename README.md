# Audio Transcription to Kiro Spec

Accelerate specs-driven development by converting spoken requirements into structured Kiro specifications that drive faster, more accurate software delivery.

A Streamlit application that captures audio input from your browser microphone or uploaded files, transcribes it using Amazon Transcribe, and converts the transcript into a structured Kiro specification format using Amazon Bedrock Claude 3.5 Sonnet.

## Features

- 🎤 **Audio Recording**: Record directly in your browser using the microphone
- 📁 **File Upload**: Upload existing .wav audio files
- 🔊 **AI Transcription**: Convert speech to text using Amazon Transcribe
- ✨ **Smart Spec Generation**: Transform requirements into structured Kiro format using Claude 3.5 Sonnet
- 📝 **Project Creation**: Automatically generate project folders with requirements.md files

## Prerequisites

### AWS Services Required

- **Amazon S3**: For audio file storage
- **Amazon Transcribe**: For speech-to-text conversion
- **Amazon Bedrock**: For Claude 3.5 Sonnet access

### AWS Permissions Required

Your AWS credentials need the following permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::your-bucket-name/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "transcribe:StartTranscriptionJob",
        "transcribe:GetTranscriptionJob"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/us.anthropic.claude-3-5-sonnet-20241022-v2:0"
    }
  ]
}
```

## Local Development Setup

### Option 1: UV Package Manager (Recommended for Development)

#### 1. Install UV

```bash
# Install uv (Python package manager)
# On macOS/Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh

# On Windows:
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or with pip:
pip install uv
```

#### 2. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/aws-samples/sample-voice-driven-development.git
cd sample-voice-driven-development

# Create virtual environment with uv
uv venv --python 3.12

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

#### 3. Install Dependencies

```bash
# Install dependencies with uv (much faster than pip)
uv sync

```

#### 4. Configure Environment Variables

```bash
# Copy environment template
cp .env.example .env

# Edit .env file with your AWS credentials
nano .env  # or use your preferred editor
```

Add your AWS credentials to `.env`:

```bash
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_SESSION_TOKEN=your_session_token_here_if_using_temporary_credentials
S3_BUCKET_NAME=your-s3-bucket-name
```

#### 5. Run the Application

```bash
# Load environment variables and run
source .env && streamlit run streamlit_app.py

# Or export variables manually
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export S3_BUCKET_NAME=your-bucket-name
streamlit run streamlit_app.py
```

The app will be available at `http://localhost:8501`

### Option 2: Docker

#### 1. Build and Run

```bash
# Build the image
docker build -t voice-driven-development .

# Run the container
docker run -p 8501:8501 \
  -e AWS_ACCESS_KEY_ID=your_access_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret_key \
  -e S3_BUCKET_NAME=your_bucket_name \
  -v $(pwd)/projects:/app/projects \
  voice-driven-development
```

## Usage

### 1. Recording Audio

- Click the "🎙️ Record Audio" tab
- Click the microphone button to start recording
- Speak your project requirements clearly
- The recording will appear when you stop

### 2. Uploading Files

- Click the "📁 Upload File" tab
- Select a .wav audio file from your computer
- Only .wav format is supported

### 3. Processing

- Click "🚀 Process Recording" or "🚀 Process Upload"
- Watch the progress through three stages:
  1. **Uploading**: Audio file uploaded to S3
  2. **Transcribing**: Speech converted to text
  3. **Generating**: Requirements document created

### 4. Results

- View the transcribed text
- Download the generated `requirements.md` file
- Find your project in the `projects/` directory

## Project Structure

```
sample-voice-driven-development/
├── streamlit_app.py          # Main Streamlit application
├── utils.py                  # AWS service utilities
├── pyproject.toml           # Python dependencies
├── Dockerfile               # Docker configuration
├── .env.example            # Environment variables template
├── .dockerignore           # Docker build exclusions
├── README.md               # This file
└── projects/               # Generated project folders
    └── your-project-name/
        └── requirements.md
```

## Environment Variables

| Variable                | Required | Description                                   |
| ----------------------- | -------- | --------------------------------------------- |
| `AWS_ACCESS_KEY_ID`     | Yes      | AWS access key                                |
| `AWS_SECRET_ACCESS_KEY` | Yes      | AWS secret key                                |
| `AWS_SESSION_TOKEN`     | No       | AWS session token (for temporary credentials) |
| `S3_BUCKET_NAME`        | Yes      | S3 bucket for audio storage                   |
| `AWS_DEFAULT_REGION`    | No       | AWS region (defaults to us-east-1)            |

## Security Notes

- Never commit AWS credentials to version control
- Use IAM roles when running on AWS infrastructure
- Regularly rotate access keys
- Use least-privilege permissions
- Audio files are temporarily stored in S3 and can be configured for automatic deletion
