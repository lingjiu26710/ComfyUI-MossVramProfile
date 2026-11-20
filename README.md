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

That multiplier is opaque, and its value differs per model family (MOSS declares 4.0, SDXL declares 0.8). At 3072×3072 it understates the activation requirement, so ComfyUI keeps more weights resident than the remaining VRAM supports:

| Render | Activations actually need | factor 4.0 reserves | Effect |
| --- | --- | --- | --- |
| 2048×2048 | ~1.3 GB | 1.3 GB | fits, fast |
| 3072×3072 | ~3.9 GB | 2.9 GB | weights and activations compete; on some builds this ends in OOM inside the FFN |

**Measurement note (2026-11-20).** On the current ComfyUI build, 3072×3072 completed without this node in 639 s, so the shortfall above does not always produce a failure. What the node changes is the resident/activation split, and that is where the timing difference in the table further down comes from.

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

Load-log excerpt from an 8 GB card at 3072×3072 (recorded 2026-11-14, on the ComfyUI build of that date):

```
factor 4.0 (old default) → 3409 MB usable, 3121 MB loaded   → OOM
factor 6.0 (≈ 4.3 GB)    → 1935 MB usable, 1647 MB loaded   → fits
```

On the build tested on 2026-11-20, the factor 4.0 case completed as well (see the comparison table below); the difference between builds is in how much the loader decides to keep resident, not in the formula.

## How it works

`memory_required()` is what ComfyUI calls before every model load and after each sampling step to decide how much VRAM the activations will need. The node replaces that method on the model instance with one that returns a fixed budget. No restart, no patching of the MOSS plugin, nothing written to disk.

`IS_CHANGED` returns `NaN` to force the node to execute every run. Without it ComfyUI caches the node and the profile would not switch when you queue a workflow at a different resolution.

## Limits

- Mutates the shared model object. Another workflow in the same ComfyUI process that lacks this node inherits whatever was set last.
- Does not touch VAE decode VRAM, which is managed separately.
- Works on any ComfyUI model (they all have `memory_required()`), but the numbers above are MOSS numbers. A model that already fits in VRAM needs nothing here.

## Comparison with other VRAM controls

Two layers affect how much weight ComfyUI keeps resident in VRAM.

| Mechanism | Layer | Scope |
| --- | --- | --- |
| `--reserve-vram N` | Global headroom subtracted before model placement | Fixed at process start |
| [ComfyUI-ReservedVRAM](https://github.com/Windecay/ComfyUI-ReservedVRAM) | The same headroom, exposed as a node | Per workflow |
| **This node** | Overrides `memory_required()` on a model instance | Per model, per execution |

Both approaches reduce resident weight and leave more room for activations. They differ in where the value is stored:

- `--reserve-vram` is a process-level constant. Changing it requires restarting ComfyUI.
- This node sets the value per execution. One session can run 1024×1024 and then 3072×3072 without a restart.

### Measured

MOSS-Image bf16, 3072×3072, 6 steps, one seed, RTX 5060 Laptop 8 GB. Each run started from a fresh ComfyUI process.

| Configuration | Result | Time |
| --- | --- | --- |
| Default, no node | success | 639 s |
| `--reserve-vram 4.5` | success | 499 s |
| This node, `reserve_gb = 4.5` | success | 490 s |

All three completed. The latter two are 22% and 23% faster than default; the 9 s gap between them is within run-to-run variation. On this configuration the two mechanisms are equivalent for throughput.

Choose by workflow: use `--reserve-vram` when one fixed headroom covers every run; add this node when the same session needs different budgets at different resolutions.

---

## 中文说明

MOSS-Image 的 bf16 权重约 10 GB，超过单卡 8 GB 的可用显存。ComfyUI 会将部分权重常驻在显存中，以减少每步的数据搬运，剩余空间留给激活。常驻比例由 MOSS 插件声明的 `memory_usage_factor = 4.0` 决定：

```
给激活预留 = latent 面积 × 每像素字节 × 0.01 × factor
```

该系数不易直接换算为显存用量，且各模型的默认值不同（MOSS 为 4.0，SDXL 为 0.8）。本节点直接以 GB 为单位指定数值。

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

数值偏大不会导致失败，但会提高权重换出 GPU 的频率，降低速度。显存足以完整加载模型时，无需添加本节点。

**局限**：改的是共享的 model 对象，同一进程里别的 workflow 会继承上一次的值；不涉及 VAE decode 的显存；对任何 ComfyUI 模型都能接，但上面那些数是 MOSS 的数。

**与其它显存控制方式的比较**：

ComfyUI 中有两个层级的手段可以影响权重常驻量，作用位置不同：

| 方式 | 作用位置 | 生效范围 |
| --- | --- | --- |
| `--reserve-vram N` | 模型加载前扣除的全局余量 | 进程启动时固定 |
| ComfyUI-ReservedVRAM | 同一余量，以节点形式提供 | 每个工作流 |
| **本节点** | 覆盖模型实例的 `memory_required()` | 每个模型、每次执行 |

两者都能降低权重常驻量、为激活腾出空间。区别在于数值存放在哪里：`--reserve-vram` 是进程级常量，修改需要重启 ComfyUI；本节点按次设置，同一会话可以先跑 1024×1024 再跑 3072×3072，不需要重启。

**实测**（MOSS-Image bf16，3072×3072，6 步，同一 seed，RTX 5060 Laptop 8 GB，每组从新进程启动）：

| 配置 | 结果 | 耗时 |
| --- | --- | --- |
| 默认，不接节点 | 成功 | 639 秒 |
| `--reserve-vram 4.5` | 成功 | 499 秒 |
| 本节点，`reserve_gb = 4.5` | 成功 | 490 秒 |

三种配置均完成出图。后两种比默认快 22% 和 23%，彼此相差 9 秒，在运行波动范围内。在这套配置上，两种方式对吞吐量的影响相当。

按工作流选择：每次运行的显存预算固定时，用 `--reserve-vram`；同一会话需要在不同分辨率下切换预算时，加本节点。
