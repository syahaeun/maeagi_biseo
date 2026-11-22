"""Local @kayahr/xbrz WASM adapter; source/license in third_party/xbrz/."""
from functools import lru_cache
from PIL import Image
from maeagi_biseo.resources import resource_path, tr


@lru_cache(maxsize=1)
def _module():
    try:
        import wasmtime
    except ImportError:
        raise ValueError(tr('editor.xbrz_unavailable')) from None
    try:
        engine = wasmtime.Engine()
        module = wasmtime.Module.from_file(engine, str(resource_path('xbrz/xbrz.wasm')))
    except (OSError, wasmtime.WasmtimeError) as exc:
        raise ValueError(tr('editor.xbrz_failed', error=str(exc))) from exc
    return engine, module


def scale_xbrz(image, factor):
    """Return genuine xBRZ RGBA output at an integer scale of 2–6."""
    if type(factor) is not int or factor not in range(2, 7):
        raise ValueError('Invalid xBRZ factor')
    width, height = image.size
    output_size = (width * factor, height * factor)
    if (min(width, height) < 1 or max(output_size) > 8192
            or output_size[0] * output_size[1] > 16_777_216):
        raise ValueError(tr('editor.upscale_too_large'))
    engine, module = _module()
    import wasmtime
    try:
        with wasmtime.Store(engine) as store:
            store.set_limits(memory_size=128 * 1024 * 1024)
            exports = wasmtime.Instance(store, module, []).exports(store)
            exports['init'](store, width, height, factor, 0)
            memory = exports['memory']
            source = exports['getSourcePointer'](store)
            target = exports['getTargetPointer'](store)
            memory.write(store, image.convert('RGBA').tobytes(), source)
            exports['scale'](store)
            data = memory.read(store, target, target + output_size[0] * output_size[1] * 4)
        return Image.frombytes('RGBA', output_size, bytes(data))
    except (wasmtime.WasmtimeError, wasmtime.Trap) as exc:
        raise ValueError(tr('editor.xbrz_failed', error=str(exc))) from exc
