# Migration guide

1. Read the research report and test evidence. Keep an independent recovery
   channel such as a provider console. Test this release in a disposable Ubuntu
   22.04.5 VM before using a production server.
2. Inspect the live unit with `systemctl cat` and `systemctl show`. Avoid sharing
   those outputs publicly: custom units can contain credentials.
3. The supported source is exactly one regular `/etc/shadowsocks-libev/NAME.json`
   file used by one active simple server unit. Only reviewed profile fields are
   allowed. The original password, method, endpoint and protocol are preserved.
4. A stock EnvironmentFile-based default unit is **not automatically migrated**.
   Its runtime options need manual review. If all semantics are represented in
   JSON, an administrator can separately prepare an explicit instance unit.
   The manager does not make that change or silently disregard DAEMON_ARGS.
5. Run `sudo bash shadowsocks-c-manager.sh migrate`. Discovery, compatibility,
   SHA-256 recording and verified backup happen before the build and cutover.
6. Review the development snapshot acknowledgement and missing-package list.
   The replacement builds, runs upstream unit/vendor tests, invokes --version
   and prepares a verified unit while the legacy service is still running.
7. Review the source path, endpoint, method, mode and backup. Type `MIGRATE`.
   The engine rechecks source bytes, stops the old unit, checks for port conflicts,
   installs separate files and starts the replacement.
8. Process identity, TCP/UDP listener ownership, service persistence and journal
   errors are checked. The source checksum must still match. Only then is legacy
   boot activation disabled and the replacement enabled.
9. Run a real client TCP and UDP relay test yourself. The manager has not done
   an end-to-end test, and never changes local or provider firewalls.

On failure after cutover, the engine stops the replacement, restores the
verified snapshot and original unit enablement/activity, then checks restored
services/sockets. It reports recovery success only when those checks pass.
If recovery fails, use the snapshot path and local journal from the console.
Do not delete either installation or manually remove the pending marker without
understanding the current state. The old package is never uninstalled.

Verify original bytes independently:

```bash
sudo sha256sum /etc/shadowsocks-libev/NAME.json
```

Compare with the SHA-256 of the corresponding evidence payload recorded in
the snapshot's structured manifest. Never print the JSON just to verify it.
