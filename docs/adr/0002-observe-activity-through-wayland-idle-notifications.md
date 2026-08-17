# Observe activity through Wayland idle notifications

The break engine will observe aggregate user activity through the compositor's `ext-idle-notify-v1` protocol and will observe suspend/resume separately through systemd-logind. This provides the threshold transitions needed for active-use Work Intervals without inspecting raw input or depending on Omarchy Shell's uptime; shorter-than-threshold idle remains intentionally indistinguishable from active use.
