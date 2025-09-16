import os

import structlog

from ..models import Config, UpdateResult
from ..utils.formatting import format_size

logger = structlog.get_logger()


class MOTDNotifier:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.motd_file = config.motd_file

    def notify(self, result: UpdateResult) -> None:
        if not self.config.notify_motd:
            return

        try:
            if not result.has_updates:
                self._remove_motd()
            else:
                self._write_motd(result)
        except Exception as e:
            logger.error("Failed to update MOTD", error=str(e))

    def _remove_motd(self) -> None:
        if self.motd_file.exists():
            try:
                os.remove(str(self.motd_file))
            except Exception:
                pass

    def _write_motd(self, result: UpdateResult) -> None:
        content = self._generate_motd(result)
        self.motd_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.motd_file, "w") as f:
            f.write(content)
        os.chmod(str(self.motd_file), 0o755)

    def _generate_motd(self, result: UpdateResult) -> str:
        lines = [
            "#!/bin/sh",
            "",
        ]

        lines.extend(
            [
                'echo ""',
                'echo "\\033[1;33m*** System Update Available ***\\033[0m"',
                f'echo "\\033[0;36m{result.summary}\\033[0m"',
                'echo ""',
            ]
        )

        if len(result.packages) <= 10:
            lines.append('echo "Packages to upgrade:"')
            for pkg in result.packages:
                size_str = f" ({pkg.display_size})" if pkg.size > 0 else ""
                lines.append(
                    f'echo "  • {pkg.name}: {pkg.current_version} → {pkg.new_version}{size_str}"'
                )
        else:
            total_size = result.total_size
            if total_size > 0:
                size_str = format_size(total_size)
                lines.append(f'echo "Total download size: {size_str}"')

        lines.extend(
            [
                'echo ""',
                'echo "Run \\033[1msudo apt upgrade\\033[0m to install updates"',
                'echo ""',
            ]
        )

        return "\n".join(lines)
