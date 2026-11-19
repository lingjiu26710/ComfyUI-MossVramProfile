# -*- coding: utf-8 -*-
"""MOSS VRAM Profile: reserve a fixed amount of VRAM for activations.

Why
---
MOSS-Image bf16 weights are ~10 GB. On an 8 GB card ComfyUI keeps a slice of
the weights resident on the GPU (so it does not have to re-upload them on every
step) and leaves the rest of VRAM for activations. That split is driven by the
`memory_usage_factor` the MOSS plugin declares (4.0), through
comfy/model_base.py:

    reserved_for_activations = latent_area * dtype_size * 0.01 * factor

The factor is an opaque multiplier, so this node skips it and sets the
reservation directly, in gigabytes:

    MOSS 3072x3072   activations need ~3.9 GB   -> reserve 4.5 GB
    MOSS 2048x2048   activations need ~1.3 GB   -> reserve 1.5 GB
    MOSS 1024x1024   activations need ~0.3 GB   -> reserve 0.5 GB

Ceiling is what the card can spare: at 3072x3072 anything past ~4.5 GB just
forces the weights off the GPU earlier and makes sampling slower.

Usage
-----
    MOSSImageUNETLoader -> [MOSS VRAM Profile] -> ModelSamplingSD3 -> ... -> KSampler

The node replaces the model's `memory_required()` with a fixed budget. ComfyUI
calls it before every model load and after each step, so no restart is needed
and switching workflows takes effect immediately. IS_CHANGED forces the node to
run every time, otherwise a cached result would win.

Set 0 to restore the model's own default.

Note: this mutates the shared model object. Another workflow in the same
ComfyUI process that does not use this node inherits the last value set.
"""


class MOSSVramProfile:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "reserve_gb": ("FLOAT", {
                    "default": 4.5, "min": 0.0, "max": 16.0, "step": 0.5,
                    "tooltip": ("VRAM to reserve for activations, in GB. "
                                "MOSS 3072px: 4.5 | 2048px: 1.5 | 1024px: 0.5. "
                                "0 = keep the model's own default. "
                                "Too high only makes it slower, never wrong output."),
                }),
            },
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "apply"
    CATEGORY = "MOSS-Image"
    DESCRIPTION = ("Reserve a fixed amount of VRAM for activations, so the weights "
                   "leave room for them. Bigger renders need more; 0 restores default.")

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Force execution every run: otherwise the node is cached and the
        # profile would not switch when a different workflow is queued.
        return float("nan")

    def apply(self, model, reserve_gb):
        inner = getattr(model, "model", model)
        if not hasattr(inner, "memory_required"):
            print("[MOSS VRAM Profile] model has no memory_required(), "
                  "not a ComfyUI model - passing through unchanged")
            return (model,)

        orig = getattr(inner, "_mossvp_orig_memory_required", None)
        if orig is None:
            orig = inner.memory_required
            inner._mossvp_orig_memory_required = orig

        if reserve_gb <= 0:
            inner.memory_required = orig
            print("[MOSS VRAM Profile] restored the model's default activation budget")
            return (model,)

        budget = int(float(reserve_gb) * (1024 ** 3))

        def _fixed_memory_required(input_shape=None, cond_shapes=None):
            return budget

        inner.memory_required = _fixed_memory_required
        print(f"[MOSS VRAM Profile] activation reserve -> {reserve_gb:.1f} GB")
        return (model,)


NODE_CLASS_MAPPINGS = {
    "MOSSVramProfile": MOSSVramProfile,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MOSSVramProfile": "MOSS VRAM Profile",
}
