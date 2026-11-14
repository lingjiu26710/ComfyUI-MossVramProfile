# ComfyUI-MossVramProfile

Per-workflow VRAM tuning for [MOSS-Image](https://github.com/wanaigc/comfyui-moss-Image) in ComfyUI. One node, one number: how much VRAM to reserve for activations, the rest goes to resident weights.

Built and verified on an RTX 5060 Laptop (8 GB) running 3072×3072 MOSS renders.

---

## The problem

MOSS-Image weights are ~10 GB in bf16, so on an 8 GB card they cannot all stay resident. ComfyUI keeps a slice of them on the GPU (cheap: no per-step upload) and leaves the rest of VRAM for activations (the intermediate tensors produced while a block is computing).

How much it keeps is decided by a constant the MOSS plugin declares, `memory_usage_factor = 4.0`, through this formula in `comfy/model_base.py`:

```
reserved_for_activations = latent_area * dtype_size * 0.01 * factor
```

That black-box coefficient works at 2048 but falls apart at 3072:

| Render | Latent | Activations actually need | factor 4.0 reserves | Outcome |
| --- | --- | --- | --- | --- |
| 2048×2048 | 128×128 | ~1.3 GB | 1.3 GB | fits, fast |
| 3072×3072 | 192×192 | ~3.9 GB | 2.9 GB | **OOM inside the FFN, 604 MB short** |

Bumping the factor in the plugin source works, but it is a global change: you have to edit a file, restart ComfyUI, and every other render is now slower for no reason. This node does it per workflow instead.

## Install

Copy this folder into `ComfyUI/custom_nodes/` and restart ComfyUI.

Requirements: a working `comfyui-moss-Image` install. No pip dependencies.

The node shows up as **MOSS VRAM Profile** under the `MOSS-Image` category.

## Usage

```
MOSSImageUNETLoader → MOSS VRAM Profile → ModelSamplingSD3 → … → KSampler
```

Put it after the MOSS loader and before anything that runs the model.

| Resolution | `memory_factor` | Notes |
| --- | --- | --- |
| 1024 / 2048 | `4.0` | MOSS default. Most weights resident, fastest. |
| 2560 | `5.0` | |
| 3072 | `6.0` | Verified: ~30 min per 30-step render on 8 GB. |
| > 3072 | up to `~8` | Ceiling is ≈8.7 at 3072²; past it the weights are fully offloaded and it only gets slower. |

On a bigger card you do not need this node at all. It is a low-VRAM tool.

## How it works

`memory_required()` is re-evaluated on every VRAM calculation, and the factor lives on the model instance (not baked into the checkpoint), so the node just writes `model.model.memory_usage_factor` before sampling starts. No restart, no patching of the MOSS plugin.

`IS_CHANGED` returns `NaN` to force the node to execute every run. Without it ComfyUI caches the node and the profile would not switch when you queue a workflow at a different resolution.

Observed effect on an 8 GB card at 3072×3072, from ComfyUI's own load log:

```
factor 4.0 → 3409 MB usable, 3121 MB loaded   → OOM
factor 6.0 → 1935 MB usable, 1647 MB loaded   → fits
```

## Limits

- Mutates the shared model object. Another workflow in the same ComfyUI process that lacks this node inherits whatever was set last.
- Does not touch VAE decode VRAM, which is managed separately.
- Only meaningful for MOSS-Image. On any other model the node prints a message and passes through unchanged.

---

## 中文说明

MOSS-Image 的权重 bf16 大约 10 GB，8G 卡装不下。ComfyUI 会把一部分权重常驻在显存里（省得每步重传），剩下的留给激活。留多少由 MOSS 插件声明的 `memory_usage_factor = 4.0` 决定，公式是：

```
给激活预留 = latent 面积 × 每像素字节 × 0.01 × factor
```

这个系数在 2048 下刚好，3072 下不够：激活实际要 3.9 GB，factor 4.0 只留 2.9 GB，于是 OOM 在 FFN 里，差 604 MB。

直接改插件源码也行，但那是全局的：要改文件、重启，之后所有图都变慢。这个节点按工作流来调。

**安装**：把整个目录拷进 `ComfyUI/custom_nodes/`，重启。需要已装 `comfyui-moss-Image`，无 pip 依赖。

**接法**：

```
MOSSImageUNETLoader → MOSS VRAM Profile → ModelSamplingSD3 → … → KSampler
```

**填法**：

| 分辨率 | memory_factor |
| --- | --- |
| 1024 / 2048 | 4.0（默认，最快） |
| 2560 | 5.0 |
| 3072 | 6.0（8G 卡实测 30 步约 30 分钟） |
| 更大 | 最多到 8 左右，再大只是变慢 |

大显存的卡用不着这个节点，它是低显存工具。

**局限**：改的是共享的 model 对象，同一进程里别的 workflow 会继承上一次的值；不涉及 VAE decode 的显存；对非 MOSS 模型只是原样透传。
