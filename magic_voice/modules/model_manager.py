"""
Model management for Chatterbox TTS Enhanced
"""
import torch
from .config import DEVICE
from chatterbox.tts import ChatterboxTTS
from chatterbox.vc import ChatterboxVC
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from chatterbox.tts_turbo import ChatterboxTurboTTS


class ModelManager:
    """Manages loading and unloading of TTS, Multilingual, and VC models."""
    
    def __init__(self):
        self.tts_model = None
        self.mtl_model = None
        self.vc_model = None
        self.turbo_model = None
        self.current_model_type = None

    def unload_all(self):
        """Unload all models to free up memory."""
        if self.tts_model is not None:
            del self.tts_model
            self.tts_model = None
        if self.mtl_model is not None:
            del self.mtl_model
            self.mtl_model = None
        if self.vc_model is not None:
            del self.vc_model
            self.vc_model = None
        if self.turbo_model is not None:
            del self.turbo_model
            self.turbo_model = None
        
        if DEVICE == "cuda":
            torch.cuda.empty_cache()
            import gc
            gc.collect()
        self.current_model_type = None
        print("🧹 Memory cleared: All models unloaded")

    def get_tts_model(self):
        """Load TTS model and unload others if needed."""
        if self.current_model_type != "tts":
            print("🔄 Switching to TTS model...")
            self.unload_all()
            try:
                self.tts_model = ChatterboxTTS.from_pretrained(DEVICE)
                self.current_model_type = "tts"
                print("✅ TTS model loaded")
            except Exception as e:
                print(f"❌ Error loading TTS model: {e}")
                return None
        return self.tts_model

    def get_mtl_model(self):
        """Load Multilingual model and unload others if needed."""
        if self.current_model_type != "mtl":
            print("🔄 Switching to Multilingual model...")
            self.unload_all()
            try:
                self.mtl_model = ChatterboxMultilingualTTS.from_pretrained(DEVICE)
                self.current_model_type = "mtl"
                print("✅ Multilingual model loaded")
            except Exception as e:
                print(f"❌ Error loading Multilingual model: {e}")
                return None
        return self.mtl_model

    def get_vc_model(self):
        """Load VC model and unload others if needed."""
        if self.current_model_type != "vc":
            print("🔄 Switching to VC model...")
            self.unload_all()
            try:
                self.vc_model = ChatterboxVC.from_pretrained(DEVICE)
                self.current_model_type = "vc"
                print("✅ VC model loaded")
            except Exception as e:
                print(f"❌ Error loading VC model: {e}")
                return None
        return self.vc_model

    def get_turbo_model(self):
        """Load Turbo model and unload others if needed."""
        if self.current_model_type != "turbo":
            print("🔄 Switching to Turbo model...")
            self.unload_all()
            try:
                self.turbo_model = ChatterboxTurboTTS.from_pretrained(device=DEVICE)
                self.current_model_type = "turbo"
                print("✅ Turbo model loaded")
            except Exception as e:
                print(f"❌ Error loading Turbo model: {e}")
                return None
        return self.turbo_model


# Global model manager instance
model_manager = ModelManager()


# Deprecated load functions (kept for compatibility but redirected)
def load_tts_model(): 
    return model_manager.get_tts_model()

def load_vc_model(): 
    return model_manager.get_vc_model()

def load_mtl_model(): 
    return model_manager.get_mtl_model()
