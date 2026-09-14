#!/usr/bin/env bash
# Build the dependency layer. Run before terraform apply.
#
# Terraform does not do this, deliberately. A pip install inside a terraform run
# is a build nobody can reproduce and a diff nobody can read: the layer's hash
# would change whenever a transitive dependency published, and an apply would
# silently redeploy code that was never reviewed.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
build="${here}/.build"
target="${build}/python"

rm -rf "${build}"
mkdir -p "${target}"

# Lambda runs on manylinux. Building on any other platform without these flags
# produces a layer that imports on the developer machine and fails in the
# deployment, which is the worst place to find out.
python -m pip install \
  --target "${target}" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.13 \
  --only-binary=:all: \
  --upgrade \
  "strands-agents>=1.53.0" "boto3>=1.40"

# boto3 and botocore ship in the Lambda runtime already, and they are the two
# largest things here. Dropping them keeps the layer under the 50 MB zipped
# limit; the runtime's copy is what the code imports.
rm -rf "${target}"/boto3 "${target}"/botocore "${target}"/boto3-* "${target}"/botocore-*
# Console scripts carry the build machine's interpreter path in their first line,
# and nothing in a layer runs them.
rm -rf "${target}/bin"
# What resolved, recorded before the metadata that says so is removed.
python -m pip list --path "${target}" --format=freeze > "${build}/deps.versions.txt"
find "${target}" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "${target}" -name "*.dist-info" -type d -prune -exec rm -rf {} + 2>/dev/null || true

# zip(1) stored modification times and filesystem order, so identical packages
# hashed differently on every build and every apply replaced the layer and
# updated all four functions. Sorted names and one fixed timestamp instead: the
# hash changes only when the packages do.
layer_hash="$(python "${here}/package_backend.py" --layer "${build}")"

printf 'layer: %s (%s, source_code_hash %s)\n' "${build}/deps.zip" "$(du -h "${build}/deps.zip" | cut -f1)" "${layer_hash}"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Dependency layer"
    echo "source_code_hash: ${layer_hash}"
    echo "Resolved packages:"
    sed 's/^/    /' "${build}/deps.versions.txt"
  } >> "${GITHUB_STEP_SUMMARY}"
fi

# Stamp the committed source, never a runtime environment variable or caller SHA.
python "${here}/package_backend.py"
