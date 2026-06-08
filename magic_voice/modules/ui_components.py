"""
UI Components for Chatterbox TTS Enhanced
Contains function to create each tab's UI layout
"""
import gradio as gr
from .config import LANGUAGE_CONFIG, SUPPORTED_LANGUAGES
from .voice_manager import load_voices, get_voices_for_language, get_all_voices_with_gender


def create_header():
    """Create the application header."""
    gr.HTML("""
        <h1 style="font-size: 2.3em; margin-bottom: 0.3rem; text-align: center;">🎙️ Chatterbox TTS - Tạo Audio &amp; Phụ Đề</h1>
        <p style='text-align: center; font-size: 1.15em; color: #3730a3; font-weight: 600; margin: 0.2rem 0;'>© 2026 Nguyễn Thăng Long — Bản quyền thuộc về Nguyễn Thăng Long · Zalo: Long Chánh Niệm</p>
        <p style='text-align: center; font-size: 1.1em; color: #666;'>Clone giọng - Tạo giọng đọc từ văn bản - Tự xuất file SRT + kiểm tra chất lượng tự động</p>
        <p style='text-align: center; font-size: 0.95em; color: #888;'>Kết quả tự lưu vào thư mục <b>outputs</b> · Mẹo: test đoạn ~150 chữ trước khi chạy cả kịch bản</p>
    """)


def create_tts_tab():
    """Create the UI for Text-to-Speech tab."""
    with gr.Row():
        with gr.Column():
            text = gr.Textbox(
                value="Hey there! I'm The Oracle Guy, and I'm unlocking the secrets of AI!",
                label="Văn bản cần đọc (không giới hạn độ dài - tool tự cắt đoạn thông minh)",
                max_lines=10,
                placeholder="Dán văn bản tiếng Anh vào đây..."
            )
            
            voice_select_tts = gr.Dropdown(
                label="Chọn giọng đọc",
                choices=get_voices_for_language("en"),
                value=f"Default ({SUPPORTED_LANGUAGES['en']})",
                info="Chọn giọng đã clone hoặc giọng có sẵn"
            )
            
            preview_audio_tts = gr.Audio(label="Nghe thử giọng", interactive=False, visible=True)
            
            gr.Markdown("**Ngôn ngữ:** Tab này chỉ dùng tiếng Anh. Ngôn ngữ khác dùng tab Đa ngôn ngữ.")
            
            exaggeration = gr.Slider(0.25, 2, step=.05, label="Exaggeration - Độ cảm xúc (0.5 = trung bình, tăng cao phải hạ CFG)", value=.5)
            cfg_weight = gr.Slider(0.0, 1, step=.05, label="CFG/Pace - Nhịp đọc (0.5 chuẩn, hạ 0.3 để chậm/diễn cảm)", value=0.5)

            with gr.Accordion("⚙️ Advanced Options", open=False):
                seed_num = gr.Number(value=0, label="Seed (0 = ngẫu nhiên; đặt số cố định để giọng ổn định)")
                temp = gr.Slider(0.05, 5, step=.05, label="Temperature - Độ biến hóa (0.8 chuẩn)", value=.8)
                min_p = gr.Slider(0.00, 1.00, step=0.01, label="min_p (0.00 disables)", value=0.05)
                top_p = gr.Slider(0.00, 1.00, step=0.01, label="top_p (1.0 disables)", value=1.00)
                repetition_penalty = gr.Slider(1.00, 2.00, step=0.1, label="Repetition Penalty - Chống lặp từ", value=1.2)

            generate_btn = gr.Button("🎙️ TẠO AUDIO", variant="primary", size="lg")
            with gr.Row():
                stop_btn_tts = gr.Button("⏸ DỪNG - nghe thử phần đã tạo", variant="stop", size="lg")
                resume_btn_tts = gr.Button("▶ TIẾP TỤC phần còn lại", variant="secondary", size="lg")

        with gr.Column():
            progress_bar_tts = gr.Slider(label="Tiến độ", minimum=0, maximum=100, value=0, interactive=False)
            status_box_tts = gr.Textbox(label="Trạng thái", value="Sẵn sàng tạo audio...", lines=3, interactive=False)
            audio_output_tts = gr.Audio(label="Audio kết quả (đã tự lưu vào thư mục outputs)", autoplay=True, show_download_button=True)

    return {
        "text": text,
        "voice_select": voice_select_tts,
        "exaggeration": exaggeration,
        "cfg_weight": cfg_weight,
        "seed_num": seed_num,
        "temp": temp,
        "min_p": min_p,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
        "generate_btn": generate_btn,
        "stop_btn": stop_btn_tts,
        "resume_btn": resume_btn_tts,
        "progress_bar": progress_bar_tts,
        "status_box": status_box_tts,
        "audio_output": audio_output_tts,
        "preview_audio": preview_audio_tts
    }


def create_multilingual_tab():
    """Create the UI for Multilingual TTS tab."""
    with gr.Row():
        with gr.Column():
            text_mtl = gr.Textbox(
                value=LANGUAGE_CONFIG["fr"]["text"],
                label="Văn bản cần đọc (không giới hạn độ dài - tool tự cắt đoạn thông minh)",
                max_lines=5,
                placeholder="Dán văn bản (ngôn ngữ bất kỳ được hỗ trợ)..."
            )
            
            language_select_mtl = gr.Dropdown(
                label="Ngôn ngữ",
                choices=[(f"{name} ({code})", code) for code, name in sorted(SUPPORTED_LANGUAGES.items())],
                value="fr",
                info="Chọn ngôn ngữ của văn bản"
            )
            
            voice_select_mtl = gr.Dropdown(
                label="Chọn giọng đọc",
                choices=get_voices_for_language("fr"),
                value=f"Default ({SUPPORTED_LANGUAGES['fr']})",
                info="Chọn giọng cho ngôn ngữ này"
            )
            
            sample_audio_mtl = gr.Audio(
                label="Nghe thử giọng",
                value=LANGUAGE_CONFIG["fr"]["audio"],
                interactive=False
            )
            
            exaggeration_mtl = gr.Slider(0.25, 2, step=.05, label="Exaggeration - Độ cảm xúc (0.5 = trung bình, tăng cao phải hạ CFG)", value=.5)
            cfg_weight_mtl = gr.Slider(0.0, 1, step=.05, label="CFG/Pace - Nhịp đọc (0.5 chuẩn, hạ 0.3 để chậm/diễn cảm)", value=0.5)

            with gr.Accordion("⚙️ Advanced Options", open=False):
                seed_num_mtl = gr.Number(value=0, label="Seed (0 = ngẫu nhiên; đặt số cố định để giọng ổn định)")
                temp_mtl = gr.Slider(0.05, 5, step=.05, label="Temperature - Độ biến hóa (0.8 chuẩn)", value=.8)

            generate_btn_mtl = gr.Button("🎙️ TẠO AUDIO", variant="primary", size="lg")
            with gr.Row():
                stop_btn_mtl = gr.Button("⏸ DỪNG - nghe thử phần đã tạo", variant="stop", size="lg")
                resume_btn_mtl = gr.Button("▶ TIẾP TỤC phần còn lại", variant="secondary", size="lg")

        with gr.Column():
            progress_bar_mtl = gr.Slider(label="Tiến độ", minimum=0, maximum=100, value=0, interactive=False)
            status_box_mtl = gr.Textbox(label="Trạng thái", value="Sẵn sàng tạo audio...", lines=3, interactive=False)
            audio_output_mtl = gr.Audio(label="Audio kết quả (đã tự lưu vào thư mục outputs)", autoplay=True, show_download_button=True)
            
            gr.Markdown(f"""
            ### Supported Languages ({len(SUPPORTED_LANGUAGES)}):
            {', '.join([f"**{name}**" for name in sorted(SUPPORTED_LANGUAGES.values())])}
            """)

    return {
        "text": text_mtl,
        "language_select": language_select_mtl,
        "voice_select": voice_select_mtl,
        "sample_audio": sample_audio_mtl,
        "exaggeration": exaggeration_mtl,
        "cfg_weight": cfg_weight_mtl,
        "seed_num": seed_num_mtl,
        "temp": temp_mtl,
        "generate_btn": generate_btn_mtl,
        "stop_btn": stop_btn_mtl,
        "resume_btn": resume_btn_mtl,
        "progress_bar": progress_bar_mtl,
        "status_box": status_box_mtl,
        "audio_output": audio_output_mtl
    }


def create_voice_conversion_tab():
    """Create the UI for Voice Conversion tab."""
    with gr.Row():
        with gr.Column():
            gr.Markdown("""
            ### Convert any voice to another!
            Upload an audio file and select a target voice to convert it.
            """)
            
            input_audio_vc = gr.Audio(
                label="File audio cần đổi giọng",
                sources=["upload", "microphone"],
                type="filepath"
            )
            
            target_voice_select = gr.Dropdown(
                label="Giọng muốn đổi sang",
                choices=["None"] + get_all_voices_with_gender(),
                value="None",
                info="Chọn giọng đích"
            )
            
            preview_audio_vc = gr.Audio(label="Nghe thử giọng đích", interactive=False, visible=True)
            
            convert_btn = gr.Button("🔄 ĐỔI GIỌNG", variant="primary", size="lg")

        with gr.Column():
            progress_bar_vc = gr.Slider(label="Tiến độ", minimum=0, maximum=100, value=0, interactive=False)
            status_box_vc = gr.Textbox(label="Trạng thái", value="Sẵn sàng đổi giọng...", lines=3, interactive=False)
            audio_output_vc = gr.Audio(label="Audio đã đổi giọng", autoplay=True, show_download_button=True)

    return {
        "input_audio": input_audio_vc,
        "target_voice_select": target_voice_select,
        "preview_audio": preview_audio_vc,
        "convert_btn": convert_btn,
        "progress_bar": progress_bar_vc,
        "status_box": status_box_vc,
        "audio_output": audio_output_vc
    }


def create_clone_voice_tab():
    """Create the UI for Clone Voice tab."""
    with gr.Row():
        with gr.Column():
            gr.Markdown("""
            ### Clone any voice instantly!
            
            **How to clone:**
            1. Upload or record a clear audio sample (5-30 seconds)
            2. Name your voice and select gender
            3. Select the language
            4. Click "Clone Voice"
            5. Use it in any tab!
            
            **Tips for best results:**
            - Use clear, high-quality audio
            - Avoid background noise
            - 10-20 seconds is ideal
            - Multiple sentences work better
            """)
            
            new_voice_name = gr.Textbox(
                label="Tên giọng (tự đặt, không dấu)",
                placeholder="Ví dụ: GiongKeChuyen, Mary..."
            )
            
            voice_gender = gr.Radio(
                label="Giới tính",
                choices=[("Male ♂️", "male"), ("Female ♀️", "female")],
                value="male",
                info="Chỉ để hiển thị"
            )
            
            voice_language = gr.Dropdown(
                label="Ngôn ngữ của giọng",
                choices=[(f"{name} ({code})", code) for code, name in sorted(SUPPORTED_LANGUAGES.items())],
                value="en",
                info="Chọn ngôn ngữ của file mẫu"
            )
            
            ref_audio_input = gr.Audio(
                label="File giọng mẫu (nên 10-20 giây, WAV sạch, không tạp âm)",
                sources=["upload", "microphone"],
                type="filepath"
            )
            clone_btn = gr.Button("🧬 TẠO GIỌNG CLONE", variant="primary", size="lg")
            
        with gr.Column():
            clone_status = gr.Textbox(label="Trạng thái clone", lines=3)
            gr.Markdown("""
            ### Your Cloned Voices:
            After cloning, your voice will appear in all tabs.
            
            **Voice Storage:**
            - Saved in `voice_samples` folder
            - Manage from this tab
            - Delete when no longer needed
            
            **Current Voices:**
            """)
            
            # Load current voices for initial display
            current_voices = load_voices()
            voices_display_text = "\n".join(current_voices) if current_voices else "No voices cloned yet"
            
            current_voices_display = gr.Textbox(
                value=voices_display_text,
                label="Các giọng đã clone",
                lines=5,
                interactive=False
            )
            
            with gr.Row():
                voice_to_delete = gr.Dropdown(
                    label="Chọn giọng muốn xóa",
                    choices=["None"] + current_voices,
                    value="None",
                    info="Chỉ xóa được giọng tự clone"
                )
                delete_btn_clone = gr.Button("🗑️ XÓA GIỌNG", variant="secondary", size="sm")
            
            delete_status_clone = gr.Textbox(label="Trạng thái xóa", lines=2)

    return {
        "new_voice_name": new_voice_name,
        "voice_gender": voice_gender,
        "voice_language": voice_language,
        "ref_audio_input": ref_audio_input,
        "clone_btn": clone_btn,
        "clone_status": clone_status,
        "current_voices_display": current_voices_display,
        "voice_to_delete": voice_to_delete,
        "delete_btn": delete_btn_clone,
        "delete_status": delete_status_clone
    }


def create_turbo_tab():
    """Create the UI for Turbo TTS tab."""
    with gr.Row():
        with gr.Column():
            gr.Markdown("""
            ### ⚡ Chatterbox-Turbo - Ultra-Fast TTS
            
            **What's New:**
            - **350M parameters** - Streamlined architecture
            - **10x faster** - One-step decoder (vs 10 steps)
            - **Native paralinguistic tags** - Add realistic emotions!
            - **Low-latency** - Perfect for voice agents
            
            **Available Paralinguistic Tags:**
            `[clear throat]` `[sigh]` `[shush]` `[cough]` `[groan]` 
            `[sniff]` `[gasp]` `[chuckle]` `[laugh]`
            
            **Example:**
            *"Hi there, Sarah here from MochaFone calling you back [chuckle], have you got one minute to chat about the billing issue?"*
            """)
            
            text_turbo = gr.Textbox(
                value="Hi there! [chuckle] I'm The Oracle Guy, and I'm unlocking the secrets of AI with Chatterbox-Turbo!",
                label="Văn bản cần đọc (không giới hạn độ dài - tool tự cắt đoạn thông minh)",
                max_lines=5,
                placeholder="Dán văn bản tiếng Anh, có thể chèn thẻ cảm xúc như [laugh] (cười), [sigh] (thở dài)...",
                elem_id="turbo_textbox"
            )
            
            # Paralinguistic tag buttons with custom styling
            gr.Markdown("**Chèn nhanh thẻ cảm xúc (bấm để thêm vào văn bản):**")
            with gr.Row(elem_classes="tag-container"):
                btn_clear_throat = gr.Button("[clear throat]", size="sm", elem_classes="tag-btn")
                btn_sigh = gr.Button("[sigh]", size="sm", elem_classes="tag-btn")
                btn_shush = gr.Button("[shush]", size="sm", elem_classes="tag-btn")
                btn_cough = gr.Button("[cough]", size="sm", elem_classes="tag-btn")
                btn_groan = gr.Button("[groan]", size="sm", elem_classes="tag-btn")
            
            with gr.Row(elem_classes="tag-container"):
                btn_sniff = gr.Button("[sniff]", size="sm", elem_classes="tag-btn")
                btn_gasp = gr.Button("[gasp]", size="sm", elem_classes="tag-btn")
                btn_chuckle = gr.Button("[chuckle]", size="sm", elem_classes="tag-btn")
                btn_laugh = gr.Button("[laugh]", size="sm", elem_classes="tag-btn")
            
            voice_select_turbo = gr.Dropdown(
                label="Chọn giọng (Turbo bắt buộc phải có giọng mẫu)",
                choices=get_voices_for_language("en"),
                value=f"Default ({SUPPORTED_LANGUAGES['en']})",
                info="Lưu ý: Turbo bỏ qua thanh Exaggeration/CFG"
            )
            
            preview_audio_turbo = gr.Audio(label="Nghe thử giọng", interactive=False, visible=True)
            
            gr.Markdown("**Ngôn ngữ:** chỉ tiếng Anh. **Lưu ý:** Turbo nhanh hơn ~4 lần nhưng không chỉnh được Exaggeration/CFG.")

            
            generate_btn_turbo = gr.Button("⚡ TẠO AUDIO (Turbo)", variant="primary", size="lg")
            with gr.Row():
                stop_btn_turbo = gr.Button("⏸ DỪNG - nghe thử phần đã tạo", variant="stop", size="lg")
                resume_btn_turbo = gr.Button("▶ TIẾP TỤC phần còn lại", variant="secondary", size="lg")

        with gr.Column():
            progress_bar_turbo = gr.Slider(label="Tiến độ", minimum=0, maximum=100, value=0, interactive=False)
            status_box_turbo = gr.Textbox(label="Trạng thái", value="Sẵn sàng tạo audio...", lines=3, interactive=False)
            audio_output_turbo = gr.Audio(label="Audio kết quả (đã tự lưu vào thư mục outputs)", autoplay=True, show_download_button=True)
            
            gr.Markdown("""
            ### 💡 Tips for Best Results:
            - Use paralinguistic tags naturally in your text
            - Tags work best mid-sentence or at natural pauses
            - Combine multiple tags for complex emotions
            - Perfect for narration, voice agents, and creative workflows
            - Generation is ~3x faster than standard model
            """)

    return {
        "text": text_turbo,
        "voice_select": voice_select_turbo,
        "preview_audio": preview_audio_turbo,
        "generate_btn": generate_btn_turbo,
        "stop_btn": stop_btn_turbo,
        "resume_btn": resume_btn_turbo,
        "progress_bar": progress_bar_turbo,
        "status_box": status_box_turbo,
        "audio_output": audio_output_turbo,
        "btn_clear_throat": btn_clear_throat,
        "btn_sigh": btn_sigh,
        "btn_shush": btn_shush,
        "btn_cough": btn_cough,
        "btn_groan": btn_groan,
        "btn_sniff": btn_sniff,
        "btn_gasp": btn_gasp,
        "btn_chuckle": btn_chuckle,
        "btn_laugh": btn_laugh
    }

