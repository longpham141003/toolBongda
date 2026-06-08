"""
Chatterbox TTS Enhanced - Main Application
A high-quality voice cloning, text-to-speech & voice conversion application
"""
import sys
import os

# Add src directory and project root to sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

src_path = os.path.join(project_root, "src")
if src_path not in sys.path:
    sys.path.append(src_path)

import gradio as gr
from modules.config import LANGUAGE_CONFIG, SUPPORTED_LANGUAGES
from modules.voice_manager import (
    load_voices, 
    get_voices_for_language, 
    get_all_voices_with_gender,
    resolve_voice_path,
    clone_voice,
    delete_voice
)
from modules.generation_functions import (
    generate_speech,
    generate_multilingual_speech,
    convert_voice,
    generate_turbo_speech,
    request_stop,
    resume_speech,
    resume_multilingual_speech,
    resume_turbo_speech
)

# Import UI components
from modules.ui_components import (
    create_header,
    create_tts_tab,
    create_multilingual_tab,
    create_voice_conversion_tab,
    create_clone_voice_tab,
    create_turbo_tab
)

# Load voices at startup
available_voices = load_voices()

# Custom CSS for Turbo tag buttons
CUSTOM_CSS = """
.tag-container {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 8px !important;
    margin-top: 5px !important;
    margin-bottom: 10px !important;
    border: none !important;
    background: transparent !important;
}
.tag-btn {
    min-width: fit-content !important;
    width: auto !important;
    height: 32px !important;
    font-size: 13px !important;
    background: #eef2ff !important;
    border: 1px solid #c7d2fe !important;
    color: #3730a3 !important;
    border-radius: 6px !important;
    padding: 0 10px !important;
    margin: 0 !important;
    box-shadow: none !important;
}
.tag-btn:hover {
    background: #c7d2fe !important;
    transform: translateY(-1px);
}
"""

# ---------------------------
# Main Application
# ---------------------------
with gr.Blocks(title="Chatterbox TTS Enhanced — © Nguyễn Thăng Long", theme=gr.themes.Soft(), css=CUSTOM_CSS) as demo:
    # State variables
    tts_model_state = gr.State(None)
    vc_model_state = gr.State(None)
    mtl_model_state = gr.State(None)
    
    # Header
    create_header()
    
    # Create tabs
    with gr.Tab("⚡ Turbo"):
        turbo_components = create_turbo_tab()

    with gr.Tab("🎤 Tạo Audio (T.Anh)"):
        tts_components = create_tts_tab()
    
    with gr.Tab("🌍 Đa ngôn ngữ"):
        mtl_components = create_multilingual_tab()
    
    with gr.Tab("🔄 Đổi giọng"):
        vc_components = create_voice_conversion_tab()
    
    with gr.Tab("🧬 Clone giọng"):
        clone_components = create_clone_voice_tab()
    
    # ---------------------------
    # Event Handlers - TTS Tab
    # ---------------------------
    tts_components['generate_btn'].click(
        fn=generate_speech,
        inputs=[
            tts_components['text'],
            tts_components['voice_select'],
            tts_components['exaggeration'],
            tts_components['temp'],
            tts_components['seed_num'],
            tts_components['cfg_weight'],
            tts_components['min_p'],
            tts_components['top_p'],
            tts_components['repetition_penalty']
        ],
        outputs=[
            tts_components['progress_bar'],
            tts_components['audio_output'],
            tts_components['status_box']
        ]
    )
    
    # Stop button (TTS): set flag, generator stops after current chunk
    tts_components['stop_btn'].click(
        fn=request_stop,
        inputs=[],
        outputs=[tts_components['status_box']],
        concurrency_limit=None
    )

    # Resume button (TTS): continue from where it stopped
    tts_components['resume_btn'].click(
        fn=resume_speech,
        inputs=[],
        outputs=[
            tts_components['progress_bar'],
            tts_components['audio_output'],
            tts_components['status_box']
        ]
    )

    # Update preview when voice changes
    def update_tts_preview(voice_name):
        path = resolve_voice_path(voice_name, "en")
        return path

    tts_components['voice_select'].change(
        fn=update_tts_preview,
        inputs=[tts_components['voice_select']],
        outputs=[tts_components['preview_audio']]
    )
    
    # ---------------------------
    # Event Handlers - Turbo Tab
    # ---------------------------
    turbo_components['generate_btn'].click(
        fn=generate_turbo_speech,
        inputs=[
            turbo_components['text'],
            turbo_components['voice_select']
        ],
        outputs=[
            turbo_components['progress_bar'],
            turbo_components['audio_output'],
            turbo_components['status_box']
        ]
    )
    
    # Stop button (Turbo): set flag, generator stops after current chunk
    turbo_components['stop_btn'].click(
        fn=request_stop,
        inputs=[],
        outputs=[turbo_components['status_box']],
        concurrency_limit=None
    )

    # Resume button (Turbo): continue from where it stopped
    turbo_components['resume_btn'].click(
        fn=resume_turbo_speech,
        inputs=[],
        outputs=[
            turbo_components['progress_bar'],
            turbo_components['audio_output'],
            turbo_components['status_box']
        ]
    )

    # Update preview when voice changes (Turbo)
    def update_turbo_preview(voice_name):
        path = resolve_voice_path(voice_name, "en")
        return path

    turbo_components['voice_select'].change(
        fn=update_turbo_preview,
        inputs=[turbo_components['voice_select']],
        outputs=[turbo_components['preview_audio']]
    )
    
    # Tag insertion buttons (Turbo) - JavaScript for cursor position
    # Using the same pattern as HuggingFace demo
    INSERT_TAG_JS = """
    (tag_val, current_text) => {
        const textarea = document.querySelector('#turbo_textbox textarea');
        if (!textarea) return current_text + " " + tag_val;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        let prefix = " ";
        let suffix = " ";
        if (start === 0) prefix = "";
        else if (current_text[start - 1] === ' ') prefix = "";
        if (end < current_text.length && current_text[end] === ' ') suffix = "";
        return current_text.slice(0, start) + prefix + tag_val + suffix + current_text.slice(end);
    }
    """
    
    # Create tag button handlers
    turbo_components['btn_clear_throat'].click(
        fn=None,
        inputs=[turbo_components['btn_clear_throat'], turbo_components['text']],
        outputs=turbo_components['text'],
        js=INSERT_TAG_JS
    )
    
    turbo_components['btn_sigh'].click(
        fn=None,
        inputs=[turbo_components['btn_sigh'], turbo_components['text']],
        outputs=turbo_components['text'],
        js=INSERT_TAG_JS
    )
    
    turbo_components['btn_shush'].click(
        fn=None,
        inputs=[turbo_components['btn_shush'], turbo_components['text']],
        outputs=turbo_components['text'],
        js=INSERT_TAG_JS
    )
    
    turbo_components['btn_cough'].click(
        fn=None,
        inputs=[turbo_components['btn_cough'], turbo_components['text']],
        outputs=turbo_components['text'],
        js=INSERT_TAG_JS
    )
    
    turbo_components['btn_groan'].click(
        fn=None,
        inputs=[turbo_components['btn_groan'], turbo_components['text']],
        outputs=turbo_components['text'],
        js=INSERT_TAG_JS
    )
    
    turbo_components['btn_sniff'].click(
        fn=None,
        inputs=[turbo_components['btn_sniff'], turbo_components['text']],
        outputs=turbo_components['text'],
        js=INSERT_TAG_JS
    )
    
    turbo_components['btn_gasp'].click(
        fn=None,
        inputs=[turbo_components['btn_gasp'], turbo_components['text']],
        outputs=turbo_components['text'],
        js=INSERT_TAG_JS
    )
    
    turbo_components['btn_chuckle'].click(
        fn=None,
        inputs=[turbo_components['btn_chuckle'], turbo_components['text']],
        outputs=turbo_components['text'],
        js=INSERT_TAG_JS
    )
    
    turbo_components['btn_laugh'].click(
        fn=None,
        inputs=[turbo_components['btn_laugh'], turbo_components['text']],
        outputs=turbo_components['text'],
        js=INSERT_TAG_JS
    )
    
    # ---------------------------
    # Event Handlers - Multilingual Tab
    # ---------------------------
    mtl_components['generate_btn'].click(
        fn=generate_multilingual_speech,
        inputs=[
            mtl_components['text'],
            mtl_components['voice_select'],
            mtl_components['language_select'],
            mtl_components['exaggeration'],
            mtl_components['temp'],
            mtl_components['seed_num'],
            mtl_components['cfg_weight']
        ],
        outputs=[
            mtl_components['progress_bar'],
            mtl_components['audio_output'],
            mtl_components['status_box']
        ]
    )
    
    # Stop button (Multilingual): set flag, generator stops after current chunk
    mtl_components['stop_btn'].click(
        fn=request_stop,
        inputs=[],
        outputs=[mtl_components['status_box']],
        concurrency_limit=None
    )

    # Resume button (Multilingual): continue from where it stopped
    mtl_components['resume_btn'].click(
        fn=resume_multilingual_speech,
        inputs=[],
        outputs=[
            mtl_components['progress_bar'],
            mtl_components['audio_output'],
            mtl_components['status_box']
        ]
    )

    # Update language change
    mtl_components['language_select'].change(
        fn=lambda lang: (
            LANGUAGE_CONFIG.get(lang, {}).get("text", ""),
            gr.update(choices=get_voices_for_language(lang), value=f"Default ({SUPPORTED_LANGUAGES.get(lang, lang)})")
        ),
        inputs=[mtl_components['language_select']],
        outputs=[mtl_components['text'], mtl_components['voice_select']]
    )
    
    # Update preview when voice changes (Multilingual)
    def update_mtl_preview(voice_name, language_code):
        path = resolve_voice_path(voice_name, language_code)
        return path

    mtl_components['voice_select'].change(
        fn=update_mtl_preview,
        inputs=[mtl_components['voice_select'], mtl_components['language_select']],
        outputs=[mtl_components['sample_audio']]
    )
    
    # ---------------------------
    # Event Handlers - Voice Conversion Tab
    # ---------------------------
    vc_components['convert_btn'].click(
        fn=convert_voice,
        inputs=[vc_components['input_audio'], vc_components['target_voice_select']],
        outputs=[vc_components['progress_bar'], vc_components['audio_output'], vc_components['status_box']]
    )
    
    # Update preview when voice changes (VC)
    def update_vc_preview(voice_name):
        if voice_name == "None": 
            return None
        
        # Remove gender symbols if present
        clean_name = voice_name.replace(" ♂️", "").replace(" ♀️", "")
        
        # Check if it's a default voice string like "Default (English)"
        if clean_name.startswith("Default ("):
            # Extract language name
            lang_name = clean_name.split("(")[1].split(")")[0]
            # Find code
            for code, name in SUPPORTED_LANGUAGES.items():
                if name == lang_name:
                    return LANGUAGE_CONFIG.get(code, {}).get("audio")
        
        # Try different possible names with gender suffixes
        from modules.voice_manager import VOICES
        possible_names = [
            clean_name,
            f"{clean_name}_male",
            f"{clean_name}_female"
        ]
        
        # Check cloned voices
        for name in possible_names:
            if name in VOICES["samples"]:
                return VOICES["samples"][name]
        
        # Try finding it with language suffixes if not found directly
        for code in SUPPORTED_LANGUAGES:
            for name in possible_names:
                full_name = f"{name}_{code}"
                if full_name in VOICES["samples"]:
                    return VOICES["samples"][full_name]
        
        return None

    vc_components['target_voice_select'].change(
        fn=update_vc_preview,
        inputs=[vc_components['target_voice_select']],
        outputs=[vc_components['preview_audio']]
    )
    
    # ---------------------------
    # Event Handlers - Clone Voice Tab
    # ---------------------------
    # Update all voice dropdowns when cloning
    clone_components['clone_btn'].click(
        fn=clone_voice,
        inputs=[
            clone_components['ref_audio_input'],
            clone_components['new_voice_name'],
            clone_components['voice_language'],
            clone_components['voice_gender']
        ],
        outputs=[clone_components['clone_status'], tts_components['voice_select']]
    ).then(
        fn=lambda: gr.update(choices=get_voices_for_language("en")),
        outputs=[tts_components['voice_select']]
    ).then(
        fn=lambda: gr.update(choices=get_voices_for_language("en")),
        outputs=[turbo_components['voice_select']]
    ).then(
        fn=lambda lang: gr.update(choices=get_voices_for_language(lang)),
        inputs=[mtl_components['language_select']],
        outputs=[mtl_components['voice_select']]
    ).then(
        fn=lambda: gr.update(choices=["None"] + get_all_voices_with_gender()),
        outputs=[vc_components['target_voice_select']]
    ).then(
        fn=lambda: "\n".join(load_voices()) if load_voices() else "No voices cloned yet",
        outputs=[clone_components['current_voices_display']]
    ).then(
        fn=lambda: gr.update(choices=["None"] + get_all_voices_with_gender(), value="None"),
        outputs=[clone_components['voice_to_delete']]
    )
    
    # Delete voice functionality in Clone Voice tab
    clone_components['delete_btn'].click(
        fn=delete_voice,
        inputs=[clone_components['voice_to_delete']],
        outputs=[clone_components['delete_status'], clone_components['voice_to_delete']]
    ).then(
        fn=lambda: gr.update(choices=get_voices_for_language("en")),
        outputs=[tts_components['voice_select']]
    ).then(
        fn=lambda: gr.update(choices=get_voices_for_language("en")),
        outputs=[turbo_components['voice_select']]
    ).then(
        fn=lambda lang: gr.update(choices=get_voices_for_language(lang)),
        inputs=[mtl_components['language_select']],
        outputs=[mtl_components['voice_select']]
    ).then(
        fn=lambda: gr.update(choices=["None"] + get_all_voices_with_gender()),
        outputs=[vc_components['target_voice_select']]
    ).then(
        fn=lambda: "\n".join(load_voices()) if load_voices() else "No voices cloned yet",
        outputs=[clone_components['current_voices_display']]
    )


    # ------- Auto-refresh voice lists every time the UI is (re)opened -------
    def _refresh_all_voices(lang):
        names = load_voices()
        return (
            gr.update(choices=get_voices_for_language("en")),
            gr.update(choices=get_voices_for_language("en")),
            gr.update(choices=get_voices_for_language(lang)),
            gr.update(choices=["None"] + get_all_voices_with_gender()),
            "\n".join(names) if names else "No voices cloned yet",
            gr.update(choices=["None"] + get_all_voices_with_gender()),
        )

    demo.load(
        fn=_refresh_all_voices,
        inputs=[mtl_components['language_select']],
        outputs=[
            tts_components['voice_select'],
            turbo_components['voice_select'],
            mtl_components['voice_select'],
            vc_components['target_voice_select'],
            clone_components['current_voices_display'],
            clone_components['voice_to_delete'],
        ],
    )


if __name__ == "__main__":
    demo.queue(
        max_size=50,
        default_concurrency_limit=1,
    ).launch(inbrowser=False, show_error=True)
