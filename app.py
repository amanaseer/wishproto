from flask import Flask, request, jsonify
import os
import openai
from azure.cognitiveservices.speech import SpeechConfig, SpeechSynthesizer, AudioConfig, SpeechSynthesisOutputFormat
from azure.storage.blob import BlobServiceClient
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
load_dotenv()  # This is the line that loads the environment variables from the .env file


app = Flask(__name__)

# Load environment variables
AZURE_SPEECH_KEY = os.getenv('AZURE_SPEECH_KEY')
AZURE_SERVICE_REGION = os.getenv('AZURE_SERVICE_REGION')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
AZURE_CONTAINER_NAME = os.getenv('AZURE_CONTAINER_NAME')
AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING')

if not AZURE_SPEECH_KEY or not AZURE_SERVICE_REGION:
    raise ValueError("Azure Speech Key and Region must be set in environment variables.")


# Configure Azure Speech service
speech_config = SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SERVICE_REGION)
speech_config.set_speech_synthesis_output_format(SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)


# Configure Blob storage
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)

# Configure OpenAI
openai.api_key = OPENAI_API_KEY

def generate_audio_from_text(text):
    """Convert text to speech and save as an MP3 file in Azure Blob Storage with specified format."""
    audio_filename = f"response-{hash(text)}.mp3"
    audio_output_path = f"./{audio_filename}"  # Adjust path as needed

    # Use global speech configuration, updating it to the desired format
    global speech_config
    speech_config.set_speech_synthesis_output_format(SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)

    # Create synthesizer with the updated configuration
    audio_config = AudioConfig(filename=audio_output_path)
    synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    
    # Synthesize the speech
    result = synthesizer.speak_text_async(text).get()
    if result.reason == ResultReason.SynthesizingAudioCompleted:
        print("Speech synthesized to audio stream.")
    elif result.reason == ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print(f"Speech synthesis canceled: {cancellation_details.reason}")
        if cancellation_details.reason == CancellationReason.Error:
            print(f"Error details: {cancellation_details.error_details}")

    # Upload the MP3 file to Azure Blob Storage
    blob_client = container_client.get_blob_client(blob=audio_filename)
    with open(audio_output_path, "rb") as audio_file:
        blob_client.upload_blob(audio_file, overwrite=True)

    # Return the URL to the MP3 file in the storage
    return blob_client.url




@app.route("/twilio/webhook", methods=['POST'])
def twilio_webhook():
    # Twilio Voice Request
    resp = VoiceResponse()
    if 'SpeechResult' in request.values:
        user_speech = request.values['SpeechResult']
        # Process with ChatGPT
        response = openai.Completion.create(
            model="gpt-3.5-turbo",
            prompt=user_speech,
            max_tokens=150
        )
        response_text = response.get('choices')[0].get('text')
        # Send response text to Azure Text to Speech
        audio_url = generate_audio_from_text(response_text)
        resp.play(audio_url)
        # Add another Gather to continue the conversation
        gather = Gather(input='speech', timeout=10, action='/twilio/webhook')
        resp.append(gather)
    else:
        # Initial prompt or re-prompt after no input
        gather = Gather(input='speech', timeout=10, action='/twilio/webhook')
        gather.say("Hello, please tell me something.")
        resp.append(gather)
    
    return str(resp)

if __name__ == "__main__":
    app.run()
