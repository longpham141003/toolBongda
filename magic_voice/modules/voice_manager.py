"""
Voice management functions for Chatterbox TTS Enhanced
"""
import os
import shutil
import tempfile
import urllib.request
import gradio as gr
from .config import VOICE_DIR, LANGUAGE_CONFIG, SUPPORTED_LANGUAGES

# Voice storage
VOICES = {"samples": {}}


def extract_gender_from_name(voice_name):
    """Extract gender from voice name if present."""
    if voice_name.endswith("_male"):
        return "male", voice_name[:-5]  # Remove _male suffix
    elif voice_name.endswith("_female"):
        return "female", voice_name[:-7]  # Remove _female suffix
    return None, voice_name


def format_voice_display_name(voice_name):
    """Format voice name with gender symbol for display."""
    gender, base_name = extract_gender_from_name(voice_name)
    if gender == "male":
        return f"{base_name} ♂️"
    elif gender == "female":
        return f"{base_name} ♀️"
    return base_name


def load_voices():
    """Load all available voice samples from the voice_samples directory."""
    VOICES["samples"].clear()
    for name in os.listdir(VOICE_DIR):
        if name.endswith(".wav"):
            base = os.path.splitext(name)[0]
            wav_path = os.path.join(VOICE_DIR, name)
            VOICES["samples"][base] = wav_path
    return list(VOICES["samples"].keys())


def get_voices_for_language(language_code):
    """Get voices available for a specific language (cloned + default sample)."""
    voices = []
    
    # Add default sample for this language if available
    if language_code in LANGUAGE_CONFIG and language_code != "en":
        voices.append(f"Default ({SUPPORTED_LANGUAGES[language_code]})")
    
    # Add cloned voices for this language
    for voice_name in VOICES["samples"].keys():
        # Check if voice has language suffix
        if voice_name.endswith(f"_{language_code}"):
            # Remove language suffix for display
            base_name = voice_name.replace(f"_{language_code}", "")
            display_name = format_voice_display_name(base_name)
            voices.append(display_name)
        elif language_code == "en":
            # For English, check if it's a voice without language suffix
            # but might have gender suffix
            # Skip if it has another language code
            has_other_lang = any(voice_name.endswith(f"_{code}") for code in SUPPORTED_LANGUAGES.keys() if code != "en")
            if not has_other_lang:
                display_name = format_voice_display_name(voice_name)
                voices.append(display_name)
    
    return voices


def resolve_voice_path(voice_name, language_code):
    """Resolve the actual voice path from display name and language."""
    if voice_name.startswith("Default ("):
        # Use default sample audio for this language
        audio_url = LANGUAGE_CONFIG.get(language_code, {}).get("audio")
        if audio_url and audio_url.startswith("http"):
            # Download the file to temp directory
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, f"chatterbox_sample_{language_code}.flac")
            
            # Download if not already cached
            if not os.path.exists(temp_file):
                try:
                    print(f"Downloading sample audio for {language_code}...")
                    urllib.request.urlretrieve(audio_url, temp_file)
                    print(f"Downloaded to {temp_file}")
                except Exception as e:
                    print(f"Error downloading audio: {e}")
                    return None
            
            return temp_file
        return audio_url
    
    # Remove gender symbol from display name if present
    clean_name = voice_name.replace(" ♂️", "").replace(" ♀️", "")
    
    # Try to find the voice with different gender suffix combinations
    possible_names = [
        clean_name,
        f"{clean_name}_male",
        f"{clean_name}_female"
    ]
    
    if language_code == "en":
        # English voices don't have language suffix
        for name in possible_names:
            if name in VOICES["samples"]:
                return VOICES["samples"][name]
    else:
        # Other languages have language suffix
        for name in possible_names:
            full_name = f"{name}_{language_code}"
            if full_name in VOICES["samples"]:
                return VOICES["samples"][full_name]
    
    return None


def get_all_voices_with_gender():
    """Get all voices formatted with gender symbols for display."""
    formatted_voices = []
    for voice_name in VOICES["samples"].keys():
        formatted_voices.append(format_voice_display_name(voice_name))
    return formatted_voices


def clone_voice(audio_file, new_voice_name, voice_language, voice_gender):
    """Clone a voice by saving the reference audio."""
    try:
        # Input validations
        if not new_voice_name or not new_voice_name.strip():
            return "❌ Error: Voice name cannot be empty.", gr.update()
        
        if not audio_file:
            return "❌ Error: No audio file provided.", gr.update()
        
        # Sanitize voice name
        new_voice_name = new_voice_name.strip()
        
        # Add gender suffix (always required now)
        new_voice_name = f"{new_voice_name}_{voice_gender}"
        
        # Add language tag for non-English voices
        if voice_language and voice_language != "en":
            new_voice_name = f"{new_voice_name}_{voice_language}"
        
        if new_voice_name in VOICES["samples"]:
            return f"❌ Error: Voice '{new_voice_name}' already exists. Please choose a different name.", gr.update()
        
        # Save the audio file
        wav_path = os.path.join(VOICE_DIR, f"{new_voice_name}.wav")
        shutil.copy(audio_file, wav_path)
        
        # Update voices dictionary
        VOICES["samples"][new_voice_name] = wav_path
        updated_voices = list(VOICES["samples"].keys())
        
        # Format display name with gender symbol
        display_name = format_voice_display_name(new_voice_name)
        
        return f"✅ Voice '{display_name}' cloned successfully!", gr.update(choices=["None"] + updated_voices, value=new_voice_name)
        
    except Exception as e:
        return f"❌ Error cloning voice: {str(e)}", gr.update()


def delete_voice(voice_name):
    """Delete a voice and its associated file."""
    try:
        if not voice_name or voice_name == "None":
            return "❌ Error: No voice selected.", gr.update()
        
        # Remove gender symbols if present
        clean_name = voice_name.replace(" ♂️", "").replace(" ♀️", "")
        
        # Try to find the actual voice name in VOICES
        actual_name = None
        possible_names = [
            clean_name,
            f"{clean_name}_male",
            f"{clean_name}_female"
        ]
        
        for name in possible_names:
            if name in VOICES["samples"]:
                actual_name = name
                break
        
        if not actual_name:
            return f"❌ Error: Voice '{voice_name}' not found.", gr.update()
        
        # Delete the file
        wav_path = VOICES["samples"][actual_name]
        if os.path.exists(wav_path):
            os.remove(wav_path)
        
        # Remove from dictionary
        del VOICES["samples"][actual_name]
        
        remaining_voices = get_all_voices_with_gender()
        new_selected = remaining_voices[0] if remaining_voices else "None"
        
        return f"✅ Voice '{voice_name}' deleted successfully!", gr.update(choices=["None"] + remaining_voices, value=new_selected)
        
    except Exception as e:
        return f"❌ Error deleting voice: {str(e)}", gr.update()
