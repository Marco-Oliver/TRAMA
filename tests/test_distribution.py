"""Release contract checks independently from the old visual regression tests."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent

class DistributionContractTests(unittest.TestCase):
    def test_clean_sources_and_local_only_credentials(self):
        content = (ROOT / 'TRAMA.spec').read_text(encoding='utf-8')
        self.assertIn('trama_launcher.py', content)
        self.assertIn('knowledge_bridge/ui', content)
        self.assertNotIn('TRAMA-Vault', content)
        self.assertNotIn('api_keys.dpapi', content)

    def test_installer_keeps_data_separate(self):
        content = (ROOT / 'TRAMA_Instalador.iss').read_text(encoding='utf-8')
        self.assertIn('PrivilegesRequired=lowest', content)
        self.assertIn('UsePreviousAppDir=yes', content)
        self.assertIn('CloseApplications=yes', content)
        self.assertIn('Source: "dist\\TRAMA\\*"', content)
        self.assertNotIn('TRAMA-Vault', content)

    def test_windows_ci_checks_actual_installation(self):
        release = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
        smoke = (ROOT / 'tools/windows_installer_smoke.ps1').read_text(encoding='utf-8')
        self.assertIn('windows-2022', release)
        self.assertIn('windows_installer_smoke.ps1', release)
        for marker in ('--self-test', 'unins000.exe', 'ci-retention-sentinel.txt', 'Start-Process'):
            self.assertIn(marker, smoke)

    def test_version_bump_and_upgrade_validation(self):
        from knowledge_bridge.update_service import VERSION
        self.assertEqual(VERSION, '2.2.4')
        iss=(ROOT/'TRAMA_Instalador.iss').read_text(encoding='utf-8')
        self.assertIn('MyAppVersion "2.2.4"',iss)
        js=(ROOT/'knowledge_bridge/ui/app.js').read_text(encoding='utf-8')
        self.assertIn('Versão instalada: 2.2.4.',js)
        script=(ROOT/'tools/windows_upgrade_smoke.ps1').read_text(encoding='utf-8')
        self.assertIn('gh release download $LegacyVersion',script)
        self.assertIn("ValidateSet('v2.1.0', 'v2.2.0', 'v2.2.1', 'v2.2.2', 'v2.2.3')",script)
        release=(ROOT/'.github/workflows/release.yml').read_text(encoding='utf-8')
        self.assertIn("windows_upgrade_smoke.ps1 -LegacyVersion 'v2.1.0'",release)
        self.assertIn("windows_upgrade_smoke.ps1 -LegacyVersion 'v2.2.0'",release)
        self.assertIn("windows_upgrade_smoke.ps1 -LegacyVersion 'v2.2.1'",release)
        self.assertIn("windows_upgrade_smoke.ps1 -LegacyVersion 'v2.2.2'",release)
        self.assertIn("windows_upgrade_smoke.ps1 -LegacyVersion 'v2.2.3'",release)
        self.assertIn('api_keys.dpapi.json',script)
        pipeline=(ROOT/'.github/workflows/full-quality-audit.yml').read_text(encoding='utf-8')
        self.assertIn('windows_upgrade_smoke.ps1',pipeline)

    def test_preview_artifact_requires_every_other_quality_gate(self):
        workflow=(ROOT/'.github/workflows/quality-main.yml').read_text(encoding='utf-8')
        self.assertIn('needs: [quality, v220-browser, v220-public-course]',workflow)
        windows=workflow.split('  v220-windows:',1)[1].split('  v220-browser:',1)[0]
        self.assertLess(windows.index('needs: [quality, v220-browser, v220-public-course]'),
                        windows.index('actions/upload-artifact@v4'))
        self.assertIn('windows_preview_smoke.ps1',windows)
        self.assertIn('SHA256SUMS-Preview.txt',windows)

    def test_readme_has_real_screenshots_and_official_download_link(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        for name in ('mapa-evolucao.png','biblioteca.png'):
            self.assertIn('docs/screenshots/' + name, readme)
            self.assertGreater((ROOT / 'docs/screenshots' / name).stat().st_size, 10000)
        self.assertIn('releases/latest/download/TRAMA_Setup.exe', readme)
        self.assertIn('Última versão', readme)
        self.assertNotIn('primeira publicação do GitHub Actions', readme)

if __name__ == '__main__': unittest.main()
