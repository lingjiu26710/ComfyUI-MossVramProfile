# -*- coding: utf-8 -*-
"""MOSS VRAM Profile: tune MOSS-Image's memory_usage_factor per workflow.

Why
---
MOSS-Image bf16 weights are ~10 GB. On an 8 GB card ComfyUI keeps a slice of
the weights resident on the GPU (so it does not have to re-upload them on every
step) and leaves the rest of VRAM for activations. That split is driven by the
`memory_usage_factor` the MOSS plugin declares (4.0), through
comfy/model_base.py:

    reserved_for_activations = latent_area * dtype_size * 0.01 * factor

At 3072x3072 the latent is 192x192, so every +1.0 of factor reserves another
~0.72 GB for activations.

    2048  latent 128x128   activations need ~1.3 GB   factor 4.0 reserves 1.3 GB, fits (fast)
    3072  latent 192x192   activations need ~3.9 GB   factor 4.0 reserves 2.9 GB -> OOM in FFN
                                                      factor 6.0 reserves 4.3 GB, weights 1.7 GB -> fits

Ceiling: about 8.7 at 3072x3072. Past that the reservation exceeds free VRAM, the
weights go fully offloaded, and it only gets slower.

Usage
-----
    MOSSImageUNETLoader -> [MOSS VRAM Profile] -> ModelSamplingSD3 -> ... -> KSampler

The node writes the value onto the model instance; `memory_required()` re-reads
it on every VRAM calculation, so no ComfyUI restart is needed and switching
workflows takes effect immediately. IS_CHANGED forces the node to run every
time, otherwise the cached value would win.

Note: this mutates the shared model object. Another workflow in the same
ComfyUI process that does not use this node inherits the last value set.
"""


class MOSSVramProfile:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "memory_factor": ("FLOAT", {
                    "default": 6.0, "min": 1.0, "max": 10.0, "step": 0.5,
                    "tooltip": ("VRAM reserved for activations, as a multiple of the "
                                "MOSS default. 2048px: 4.0 (more resident weights, fast). "
                                "3072px: 6.0. Ceiling ~8.7 at 3072px, beyond that only slower."),
                }),
            },
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "apply"
    CATEGORY = "MOSS-Image"
    DESCRIPTION = ("Tune MOSS-Image memory_usage_factor: how much VRAM is reserved for "
                   "activations, the rest goes to resident weights.")

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Force execution every run: otherwise the node is cached and the
        # profile would not switch when a different workflow is queued.
        return float("nan")

    def apply(self, model, memory_factor):
        inner = getattr(model, "model", model)
        if hasattr(inner, "memory_usage_factor"):
            old = inner.memory_usage_factor
            inner.memory_usage_factor = float(memory_factor)
            print(f"[MOSS VRAM Profile] memory_usage_factor {old} -> {memory_factor}")
        else:
            print("[MOSS VRAM Profile] model has no memory_usage_factor, "
                  "this is not a MOSS-Image model - passing through unchanged")
        return (model,)


NODE_CLASS_MAPPINGS = {
    "MOSSVramProfile": MOSSVramProfile,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MOSSVramProfile": "MOSS VRAM Profile",
}
