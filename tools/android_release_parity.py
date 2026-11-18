"""Compare two downloaded Android release directories offline; never publishes."""
import argparse
import json
from pathlib import Path
import subprocess

from android_artifacts import VerificationError, validate_release_bundle


def compare_releases(github, gitee=None):
    official = validate_release_bundle(github)
    if gitee is None:
        return {"status": "NOT_CONFIGURED", "message": "未提供 Gitee 下载目录，尚未验证双平台一致性。",
                "github": str(Path(github).resolve()), "dualPlatformVerified": False}
    mirror = validate_release_bundle(gitee)
    differences = []
    for key in sorted(set(official["metadata"]) | set(mirror["metadata"])):
        if official["metadata"].get(key) != mirror["metadata"].get(key):
            differences.append(f"android-release.json: {key}")
    # Mirror the original bundle verbatim, including verification evidence and provenance.
    for filename in sorted(set(official["fileSha256"]) | set(mirror["fileSha256"])):
        if official["fileSha256"].get(filename) != mirror["fileSha256"].get(filename):
            differences.append(f"file bytes: {filename}")
    return {"status": "FAIL" if differences else "PASS", "differences": differences,
            "github": official["directory"], "gitee": mirror["directory"],
            "scope": "local-directories-only", "dualPlatformVerified": False,
            "localBundlesIdentical": not differences,
            "message": "本地发行文件比较；不证明远程仓库已同步。"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github", type=Path, required=True)
    parser.add_argument("--gitee", type=Path, help="Omit to report NOT_CONFIGURED (exit 2)")
    args = parser.parse_args(argv)
    try:
        result = compare_releases(args.github, args.gitee)
    except (VerificationError, OSError, ValueError, subprocess.SubprocessError) as error:
        result = {"status": "FAIL", "message": str(error), "dualPlatformVerified": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {"PASS": 0, "FAIL": 1, "NOT_CONFIGURED": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
