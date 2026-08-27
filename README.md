<p align="center">
  <img src="assets/logo.png" alt="Zhūquè-Mur" width="240">
</p>

# Zhūquè-Mur

A Python CLI for **legal clean-room reimplementation**.

Check the license. Keep analysis and implementation apart with isolated AI agents. Produce code you can license as your own.

The wall: the analyst may read the original. The implementer may read only the spec.

See [docs/README.md](docs/README.md) for the process, rooms, and commands.

```bash
poetry install
copy .env.example .env
.\scripts\install-path.ps1
zhuque
```

The everyday command is `zhuque`. `zhuque-mur`, `zhu-mur`, and `zhu` are the same program.

Then `auth login <subscription>` (OAuth) or `auth byok <inference_provider>` (bring your own key).
