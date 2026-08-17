# Break enforcement fails open

OmookAway will enforce a Break only while every required overlay surface is healthy; a launch failure, crashed surface, or uncovered display releases input, leaves the Break unsatisfied, and returns the engine to a degraded Warning instead of maintaining a partial lock. Strong friction is the product's purpose, but preserving control of the desktop and reporting recovery truthfully take priority over enforcement.
