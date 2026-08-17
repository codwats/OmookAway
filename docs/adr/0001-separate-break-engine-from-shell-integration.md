# Separate the break engine from Omarchy Shell integration

OmookAway will keep timing and state in a standalone daemon, launch Break overlays in a dedicated Quickshell process, and use an Omarchy Shell plugin only as a thin status and control interface. Putting the entire product inside the Shell plugin would be simpler, but a Shell restart or crash could otherwise discard timer state or terminate an enforced Break; the independent lifecycle is worth the additional process boundary.
