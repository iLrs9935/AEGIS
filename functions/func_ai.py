# functions/func_ai.py
import gc
import importlib.util
import os
import sys
from pathlib import Path

from core.event_bus import bus

# ========================================================
# --- 物理破壁：双轨制 DLL 注入 (兼容 Dev 源码与 EXE 运行) ---
# ========================================================


_DLL_HANDLES = []


def inject_dll_environment():
    """Discover the active environment; keep DLL directory handles alive."""
    override = os.environ.get("AEGIS_LLAMA_LIB", "").strip()
    if override:
        llama_lib = Path(override)
    elif hasattr(sys, "_MEIPASS"):
        llama_lib = Path(sys._MEIPASS) / "dlls"
    else:
        spec = importlib.util.find_spec("llama_cpp")
        llama_lib = (
            Path(spec.origin).parent / "lib"
            if spec and spec.origin
            else Path(__file__).resolve().parents[1] / "dlls"
        )

    candidates = [llama_lib]
    cuda_root = os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME")
    if cuda_root:
        candidates.extend([Path(cuda_root) / "bin", Path(cuda_root) / "bin" / "x64"])
    existing = [str(path) for path in candidates if path.is_dir()]
    if hasattr(os, "add_dll_directory"):
        for path in existing:
            _DLL_HANDLES.append(os.add_dll_directory(path))
    if existing:
        os.environ["PATH"] = os.pathsep.join(existing + [os.environ.get("PATH", "")])
    return str(llama_lib)


# 启动时执行注入，并获取实际生效的 llama_lib 路径
ACTUAL_LLAMA_LIB = inject_dll_environment()

# 全局显存单例
GLOBAL_LLM_ENGINE = None


def load_model(model_path, n_gpu_layers=35, n_ctx=4096):
    """加载模型到显存"""
    global GLOBAL_LLM_ENGINE
    if GLOBAL_LLM_ENGINE is not None:
        bus.log_emitted.emit("INFO", "AI_HAL", "模型已在显存中待命，无需重复加载。")
        return True

    try:
        from llama_cpp import Llama

        bus.log_emitted.emit(
            "WARN", "AI_HAL", f"🔥 正在将模型载入显存 (层数: {n_gpu_layers})..."
        )
        GLOBAL_LLM_ENGINE = Llama(
            model_path=model_path,
            n_gpu_layers=int(n_gpu_layers),
            n_ctx=int(n_ctx),
            verbose=False,
        )
        bus.log_emitted.emit("SUCCESS", "AI_HAL", "✅ AI 核心点火成功！")
        return True
    except Exception as e:
        bus.log_emitted.emit("ERROR", "AI_HAL", f"❌ 模型加载失败: {e}")
        return False


def unload_model():
    """核爆级清理：将模型踢出显存，为游戏让路"""
    global GLOBAL_LLM_ENGINE
    if GLOBAL_LLM_ENGINE is not None:
        del GLOBAL_LLM_ENGINE
        GLOBAL_LLM_ENGINE = None
        gc.collect()  # 强制 Python 垃圾回收，释放 C++ 指针
        bus.log_emitted.emit("SUCCESS", "AI_HAL", "♻️ AI 核心已卸载，显存已释放。")
    return True


# functions/func_ai.py (更新 generate_chat 函数)


def generate_chat(prompt_or_messages, max_tokens=150, temperature=0.3):
    """现代化的对话式推理：自适应字符串或对话记忆数组"""
    global GLOBAL_LLM_ENGINE
    if GLOBAL_LLM_ENGINE is None:
        raise RuntimeError("模型未加载！请先执行[加载大模型]节点。")

    # 核心判断逻辑下沉到 Func
    if isinstance(prompt_or_messages, str):
        # 如果是没连记忆节点的单行文本，直接包成单次对话
        messages = [{"role": "user", "content": prompt_or_messages}]
    elif isinstance(prompt_or_messages, list):
        # 如果是连了记忆节点传来的完整数组，直接拿来用
        messages = prompt_or_messages
    else:
        raise ValueError("Prompt 格式错误，必须是字符串(str)或数组(list)")

    output = GLOBAL_LLM_ENGINE.create_chat_completion(
        messages=messages, max_tokens=int(max_tokens), temperature=float(temperature)
    )

    return output["choices"][0]["message"]["content"].strip()
