"""
Configuration and constants for Chatterbox TTS Enhanced
"""
import os
import torch
from pathlib import Path

# Project paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
VOICE_DIR = os.path.join(PROJECT_ROOT, "voice_samples")
os.makedirs(VOICE_DIR, exist_ok=True)

# Device configuration
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Check GPU memory and fallback to CPU if less than 5GB
if DEVICE == "cuda":
    gpu_memory_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
    if gpu_memory_gb < 5:
        print("=" * 50)
        print(f"⚠️  WARNING: GPU memory ({gpu_memory_gb:.2f} GB) is less than 5GB")
        print("⚠️  Switching to CPU to avoid out-of-memory errors")
        print("=" * 50)
        DEVICE = "cpu"

# Print device information
print("=" * 50)
print(f"🚀 Chatterbox TTS Enhanced Starting...")
print(f"📱 Device: {DEVICE.upper()}")
if DEVICE == "cuda":
    print(f"🎮 GPU: {torch.cuda.get_device_name(0)}")
    print(f"💾 GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
    print("✅ GPU has sufficient memory (≥5GB)")
else:
    if torch.cuda.is_available():
        print(f"⚠️  GPU available but using CPU due to low memory")
        print(f"🎮 GPU: {torch.cuda.get_device_name(0)}")
        print(f"💾 GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB (< 5GB required)")
    else:
        print("⚠️  No GPU detected - Running on CPU")
    print("⏱️  Generation will be slower on CPU")
print("=" * 50)
print()

# Supported languages from chatterbox.mtl_tts
from chatterbox.mtl_tts import SUPPORTED_LANGUAGES

# Language configuration with sample audio and text
LANGUAGE_CONFIG = {
    "ar": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/ar_f/ar_prompts2.flac", "text": "مرحبًا! أنا The Oracle Guy وأنا هنا لفتح أسرار الذكاء الاصطناعي! اشترك الآن وانضم إلى ثورة الذكاء الاصطناعي!"},
    "da": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/da_m1.flac", "text": "Hej! Jeg er The Oracle Guy, og jeg låser op for AI's hemmeligheder! Abonner nu og bliv en del af AI-revolutionen!"},
    "de": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/de_f1.flac", "text": "Hallo! Ich bin The Oracle Guy und ich entschlüssele die Geheimnisse der KI! Abonniere jetzt und werde Teil der KI-Revolution!"},
    "el": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/el_m.flac", "text": "Γεια σας! Είμαι ο The Oracle Guy και ξεκλειδώνω τα μυστικά της τεχνητής νοημοσύνης! Εγγραφείτε τώρα και γίνετε μέρος της επανάστασης AI!"},
    "en": {"text": "Hey there! I'm The Oracle Guy, and I'm unlocking the secrets of AI! Subscribe now and join the AI revolution!"},
    "es": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/es_f1.flac", "text": "¡Hola! Soy The Oracle Guy y estoy desbloqueando los secretos de la IA! ¡Suscríbete ahora y únete a la revolución de la IA!"},
    "fi": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/fi_m.flac", "text": "Hei! Olen The Oracle Guy ja avaan tekoälyn salaisuudet! Tilaa nyt ja liity tekoälyvallankumoukseen!"},
    "fr": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/fr_f1.flac", "text": "Salut! Je suis The Oracle Guy et je déverrouille les secrets de l'IA! Abonnez-vous maintenant et rejoignez la révolution de l'IA!"},
    "he": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/he_m1.flac", "text": "שלום! אני The Oracle Guy ואני פותח את סודות הבינה המלאכותית! הירשם עכשיו והצטרף למהפכת הבינה המלאכותית!"},
    "hi": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/hi_f1.flac", "text": "नमस्ते! मैं द ओरेकल गाय हूँ और मैं एआई के रहस्यों को खोल रहा हूँ! अभी सब्सक्राइब करें और एआई की क्रांति में शामिल हों!"},
    "it": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/it_m1.flac", "text": "Ciao! Sono The Oracle Guy e sto sbloccando i segreti dell'IA! Iscriviti ora e unisciti alla rivoluzione dell'IA!"},
    "ja": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/ja/ja_prompts1.flac", "text": "こんにちは！私はThe Oracle Guyです。AIの秘密を解き明かしています！今すぐチャンネル登録してAI革命に参加しましょう！"},
    "ko": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/ko_f.flac", "text": "안녕하세요! 저는 The Oracle Guy이고 AI의 비밀을 풀고 있습니다! 지금 구독하고 AI 혁명에 동참하세요!"},
    "ms": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/ms_f.flac", "text": "Hai! Saya The Oracle Guy dan saya membuka rahsia AI! Langgan sekarang dan sertai revolusi AI!"},
    "nl": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/nl_m.flac", "text": "Hallo! Ik ben The Oracle Guy en ik ontgrendel de geheimen van AI! Abonneer nu en word deel van de AI-revolutie!"},
    "no": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/no_f1.flac", "text": "Hei! Jeg er The Oracle Guy og jeg låser opp hemmelighetene til AI! Abonner nå og bli med på AI-revolusjonen!"},
    "pl": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/pl_m.flac", "text": "Cześć! Jestem The Oracle Guy i odkrywam tajemnice sztucznej inteligencji! Subskrybuj teraz i dołącz do rewolucji AI!"},
    "pt": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/pt_m1.flac", "text": "Olá! Eu sou The Oracle Guy e estou a desbloquear os segredos da IA! Subscreve agora e junta-te à revolução da IA!"},
    "ru": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/ru_m.flac", "text": "Привет! Я The Oracle Guy и я раскрываю секреты искусственного интеллекта! Подпишись сейчас и присоединяйся к революции ИИ!"},
    "sv": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/sv_f.flac", "text": "Hej! Jag är The Oracle Guy och jag låser upp AI:s hemligheter! Prenumerera nu och gå med i AI-revolutionen!"},
    "sw": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/sw_m.flac", "text": "Habari! Mimi ni The Oracle Guy na ninafungua siri za AI! Jiandikishe sasa na ujiunga na mapinduzi ya AI!"},
    "tr": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/tr_m.flac", "text": "Merhaba! Ben The Oracle Guy ve yapay zekanın sırlarını açığa çıkarıyorum! Şimdi abone ol ve yapay zeka devrimine katıl!"},
    "zh": {"audio": "https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/zh_f2.flac", "text": "大家好！我是The Oracle Guy，我正在解锁人工智能的秘密！立即订阅并加入人工智能革命！"},
}
