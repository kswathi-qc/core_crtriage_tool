# Functionality → Tech Team map

Source of truth for routing a CR's `ChangeRequestParticipant.Functionality`
value (from Orbit) to the tech-team folder under `tech-teams/` whose
`README.md` defines the debug-info rules to apply.

Lookup is exact, case-insensitive match on the `Functionality` column.

| Functionality (Orbit) | Tech Team | Folder |
|---|---|---|
| Baseport | Kernel | `tech-teams/kernel/` |
| MPROC | Kernel | `tech-teams/kernel/` |
| HLOS RmNet | Kernel | `tech-teams/kernel/` |
| Linux PM | Kernel | `tech-teams/kernel/` |
| Tools | Kernel | `tech-teams/kernel/` |
| FLASH | Kernel | `tech-teams/kernel/` |
| diag | Kernel | `tech-teams/kernel/` |
| Thermal Management | Kernel | `tech-teams/kernel/` |
| USB | Kernel | `tech-teams/kernel/` |
| CLOCK | Kernel | `tech-teams/kernel/` |
| PCIe | Kernel | `tech-teams/kernel/` |
| I2C | Kernel | `tech-teams/kernel/` |
| Coresight | Kernel | `tech-teams/kernel/` |
| TLMM | Kernel | `tech-teams/kernel/` |
| RPM | Kernel | `tech-teams/kernel/` |
| UART | Kernel | `tech-teams/kernel/` |
| TFA-BL31 | Security | `tech-teams/security/` |
| WIN TME | Security | `tech-teams/security/` |
| OPTEE | Security | `tech-teams/security/` |
| ARM Trusted Firmware | Security | `tech-teams/security/` |
| TZBSP | Security | `tech-teams/security/` |
| Platform support | OpenWRT | `tech-teams/openwrt/` |
| Q6-COREIMG | Q6 | `tech-teams/q6/` |
| Triage | Triage | `tech-teams/triage/` |
| UBoot | U-Boot | `tech-teams/u-boot/` |
| xBL | Boot | `tech-teams/boot/` |
| DDR | Boot | `tech-teams/boot/` |
| PWM | Kernel | `tech-teams/kernel/` |
| PCM | Kernel | `tech-teams/kernel/` |
| HWENGINES-BAM | Kernel | `tech-teams/kernel/` |

If a CR's `Functionality` value is not in this table, do not guess a team.
Skip the automatic tag/reassign/comment actions for that CR and flag it in the
run summary as "unmapped functionality — needs a table entry" so the mapping
can be extended.
