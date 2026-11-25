# Interaction design

Three primary modes are shared by CLI and GUI. The desktop uses a dark navy
workspace, cyan accent, generous spacing, descriptive status badges and a live
event console. Labels communicate state without color. Keyboard focus, tab
order, labelled controls and resizable panels support keyboard operation.

Inspection is available without root; administration requires the Ubuntu target.
Forms validate before execution. Passwords stay masked and travel through stdin,
never process arguments. Migration loads a source path, not editable credentials.
The activity panel reports completed steps and pending confirmations. Risky
actions require exact typed words after showing affected paths and services.
Cancel requests termination and recovery, without claiming immediate reversal.
Windows displays an explicit read-only inspection status.

For the primary deployment, Python and the engine run on Ubuntu while MobaXterm
displays the window through SSH/X11. The GUI shows a forwarded-display badge and
retains administrative controls for the root Ubuntu process. The launcher gives
actionable terminal errors before Qt startup for absent display, missing authority,
failed authorization or missing xcb libraries. It never prints cookie values.

No remote connectivity, accessibility certification or usability measurement is
claimed. Qt offscreen smoke tests complement, but do not replace, target-host
keyboard, screen reader and systemd integration testing.
