# ComfyUI-MossVramProfile

Give a ComfyUI model a fixed VRAM budget for activations, in gigabytes. Built for [MOSS-Image](https://github.com/wanaigc/comfyui-moss-Image) on 8 GB cards.

Verified on an RTX 5060 Laptop (8 GB): 3072×3072 MOSS renders, and a pass-through run on SDXL (Illustrious XL Q8 GGUF).

---

## The problem

MOSS-Image weights are ~10 GB in bf16, so on an 8 GB card they cannot all stay resident. ComfyUI keeps a slice of them on the GPU (cheap: no per-step upload) and leaves the rest of VRAM for activations (the intermediate tensors produced while a block is computing).

The split is decided by a multiplier the MOSS plugin declares, `memory_usage_factor = 4.0`, through this formula in `comfy/model_base.py`:

```
reserved_for_activations = latent_area * dtype_size * 0.01 * factor
```

That multiplier is opaque, and its value differs per model family (MOSS declares 4.0, SDXL declares 0.8). It works at 2048 and falls apart at 3072:

| Render | Activations actually need | factor 4.0 reserves | Outcome |
| --- | --- | --- | --- |
| 2048×2048 | ~1.3 GB | 1.3 GB | fits, fast |
| 3072×3072 | ~3.9 GB | 2.9 GB | **OOM inside the FFN, 604 MB short** |

This node drops the multiplier and asks you for the number directly, in GB.

## Install

Copy this folder into `ComfyUI/custom_nodes/` and restart ComfyUI.

Requirements: a working `comfyui-moss-Image` install. No pip dependencies.

The node shows up as **MOSS VRAM Profile** under the `MOSS-Image` category.

## Usage

```
MOSSImageUNETLoader → MOSS VRAM Profile → ModelSamplingSD3 → … → KSampler
```

Put it after the model loader and before anything that runs the model.

| Render | `reserve_gb` | Notes |
| --- | --- | --- |
| 1024×1024 | `0.5` | |
| 2048×2048 | `1.5` | |
| 3072×3072 | `4.5` | Verified: ~30 min per 30-step render on 8 GB. |
| any | `0` | Restore the model's own default. |

Too high is never wrong, only slower: a bigger reservation just pushes the weights off the GPU sooner. On a card with enough VRAM for the whole model, leave the node out entirely.

Observed effect on an 8 GB card at 3072×3072, from ComfyUI's own load log:

```
factor 4.0 (old default) → 3409 MB usable, 3121 MB loaded   → OOM
factor 6.0 (≈ 4.3 GB)    → 1935 MB usable, 1647 MB loaded   → fits
```

## How it works

`memory_required()` is what ComfyUI calls before every model load and after each sampling step to decide how much VRAM the activations will need. The node replaces that method on the model instance with one that returns a fixed budget. No restart, no patching of the MOSS plugin, nothing written to disk.

`IS_CHANGED` returns `NaN` to force the node to execute every run. Without it ComfyUI caches the node and the profile would not switch when you queue a workflow at a different resolution.

## Limits

- Mutates the shared model object. Another workflow in the same ComfyUI process that lacks this node inherits whatever was set last.
- Does not touch VAE decode VRAM, which is managed separately.
- Works on any ComfyUI model (they all have `memory_required()`), but the numbers above are MOSS numbers. A model that already fits in VRAM needs nothing here.

## How this differs from other VRAM tools

| Tool | What it controls | Where it acts |
| --- | --- | --- |
| ComfyUI `--reserve-vram` | Headroom kept away from *all* models | Launch flag |
| [ComfyUI-ReservedVRAM](https://github.com/Windecay/ComfyUI-ReservedVRAM) | The same headroom, adjustable from a node | Per workflow |
| VRAM Optimizer / cache clearers | Frees cached VRAM between runs | Per queue |
| **This node** | What a *specific model* declares its activations need | Inside the model instance |

The last row is the difference. `--reserve-vram` and ReservedVRAM both work *outside* the model: they reserve a slice of the card and hope the rest fits. This node overrides `memory_required()` on the model object, which is the number ComfyUI itself uses to compute `lowvram_model_memory`.

That only matters when the declaration is wrong. MOSS declares `memory_usage_factor = 4.0`, which tells ComfyUI to keep roughly 3.1 GB of weights resident on an 8 GB card and leaves too little for activations at 3072×3072. No amount of external reservation fixes a bad declaration — you have to change the declaration.

So: if the problem is "something else on this machine is eating VRAM", use `--reserve-vram` or ReservedVRAM. If the problem is "this model asks for the wrong amount", this node is the inside job.

---

## 中文说明

MOSS-Image 的权重 bf16 大约 10 GB，8G 卡装不下。ComfyUI 会把一部分权重常驻在显存里（省得每步重传），剩下的留给激活。留多少由 MOSS 插件声明的 `memory_usage_factor = 4.0` 这个倍数决定：

```
给激活预留 = latent 面积 × 每像素字节 × 0.01 × factor
```

倍数太绕，而且每个模型的默认值不一样（MOSS 是 4.0，SDXL 是 0.8）。这个节点直接问你要多少 GB。

**安装**：整个目录拷进 `ComfyUI/custom_nodes/`，重启。需要已装 `comfyui-moss-Image`，无 pip 依赖。

**接法**：

```
MOSSImageUNETLoader → MOSS VRAM Profile → ModelSamplingSD3 → … → KSampler
```

**填法**：

| 分辨率 | reserve_gb |
| --- | --- |
| 1024×1024 | 0.5 |
| 2048×2048 | 1.5 |
| 3072×3072 | 4.5（8G 卡实测 30 步约 30 分钟） |
| 任意 | 0 = 恢复模型自己的默认值 |

填大了不会出错，只会变慢：预留越多，权重被赶下 GPU 越早。显存本来就能整装模型的卡，别放这个节点。

**局限**：改的是共享的 model 对象，同一进程里别的 workflow 会继承上一次的值；不涉及 VAE decode 的显存；对任何 ComfyUI 模型都能接，但上面那些数是 MOSS 的数。

**和别的显存工具的区别**：

- `--reserve-vram`（ComfyUI 的启动参数）和 [ComfyUI-ReservedVRAM](https://github.com/Windecay/ComfyUI-ReservedVRAM) 都是在**模型外面**留一块地盘，剩下的指望装得下。
- 这个节点是在**模型里面**改它自己声明的 `memory_required()`，也就是 ComfyUI 算 `lowvram_model_memory` 用的那个数。
- 判断标准很简单：别的程序占了显存 → 用 reserve-vram 或 ReservedVRAM；**模型自己报的数不对** → 用这个。MOSS 报 `memory_usage_factor = 4.0` 那份声明，就是报错了，在它外面怎么留地盘都治不了。
