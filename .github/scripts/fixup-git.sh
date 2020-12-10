#!/bin/bash

set -e

# Disable prompting for passwords - works with git version 2.3 or above
export GIT_TERMINAL_PROMPT=0
# Harder core version of disabling the username/password prompt.
GIT_CREDENTIAL_HELPER=$PWD/.git/git-credential-stop
cat > $GIT_CREDENTIAL_HELPER <<EOF
cat
echo "username=git"
echo "password=git"
EOF
chmod a+x $GIT_CREDENTIAL_HELPER
git config credential.helper $GIT_CREDENTIAL_HELPER

# Create a global .gitignore and populate with Python stuff
GIT_GLOBAL_IGNORE=$PWD/.git/ignore
cat > $GIT_GLOBAL_IGNORE <<EOF
# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]

# Distribution / packaging
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
pip-wheel-metadata/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST
EOF
git config --global core.excludesfile $GIT_GLOBAL_IGNORE

DF_BEFORE_GIT="$(($(stat -f --format="%a*%S" .)))"

echo ""
echo ""
echo ""
echo "- Fetching non shallow to get git version"
echo "---------------------------------------------"
if git rev-parse --is-shallow-repository; then
	git fetch origin --unshallow
fi
git fetch origin --tags

GITHUB_COMMIT_ACTUAL=$(git log --pretty=format:'%H' -n 1)

if [ "$GITHUB_EVENT_NAME" == "pull_request" ]; then
	GITHUB_PR_NUMBER = $(echo $GITHUB_REF | awk 'BEGIN { FS = "/" } ; { print $3 }')
	echo ""
	echo ""
	echo ""
	echo "- Fetching from pull request source"
	echo "---------------------------------------------"
	git remote add source https://github.com/$GITHUB_PR_NUMBER.git
	git fetch source && git fetch --tags

	echo ""
	echo ""
	echo ""
	echo "- Fetching the actual pull request"
	echo "---------------------------------------------"
	git fetch origin pull/$GITHUB_PR_NUMBER/head:pull-$GITHUB_PR_NUMBER-head
	git fetch origin pull/$GITHUB_PR_NUMBER/merge:pull-$GITHUB_PR_NUMBER-merge
	echo "---------------------------------------------"
	git log -n 5 --graph pull-$GITHUB_PR_NUMBER-head
	echo "---------------------------------------------"
	git log -n 5 --graph pull-$GITHUB_PR_NUMBER-merge
	echo "---------------------------------------------"

	GITHUB_CURRENT_MERGE_SHA1="$(git log --pretty=format:'%H' -n 1 pull-$GITHUB_PR_NUMBER-merge)"
	if [ "$GITHUB_CURRENT_MERGE_SHA1" != "$GITHUB_SHA" ]; then
		echo ""
		echo ""
		echo ""
		echo "- Pull request triggered for $GITHUB_SHA but now at $GITHUB_CURRENT_MERGE_SHA1"
		echo ""
	fi
	if [ "$GITHUB_CURRENT_MERGE_SHA1" != "$GITHUB_COMMIT_ACTUAL" ]; then
		echo ""
		echo ""
		echo ""
		echo "- Pull request triggered for $GITHUB_COMMIT_ACTUAL but now at $GITHUB_CURRENT_MERGE_SHA1"
		echo ""
	fi

	echo ""
	echo ""
	echo ""
	echo "- Using pull request version of submodules (if they exist)"
	echo "---------------------------------------------"
	$PWD/.github/scripts/add-local-submodules.sh $GITHUB_REPOSITORY
	echo "---------------------------------------------"
	git submodule foreach --recursive 'git remote -v; echo'
	echo "---------------------------------------------"
fi

if [ z"$GITHUB_REPOSITORY" != z ]; then
	echo ""
	echo ""
	echo ""
	echo "- Using local version of submodules (if they exist)"
	echo "---------------------------------------------"
	$PWD/.github/scripts/add-local-submodules.sh $GITHUB_REPOSITORY
	echo "---------------------------------------------"
	git submodule foreach --recursive 'git remote -v; echo'
	echo "---------------------------------------------"
fi

echo "---------------------------------------------"
git submodule status --recursive
echo "---------------------------------------------"

if [ "$GITHUB_COMMIT_ACTUAL" != "$GITHUB_SHA" ]; then
	echo ""
	echo ""
	echo ""
	echo "- Build request triggered for $GITHUB_SHA but got $GITHUB_COMMIT_ACTUAL"
	echo ""
	GITHUB_SHA=$GITHUB_COMMIT_ACTUAL
fi

if [ z"$GITHUB_BRANCH" != z ]; then
	echo ""
	echo ""
	echo ""
	echo "Fixing detached head (current $GITHUB_COMMIT_ACTUAL)"
	echo "---------------------------------------------"
	git log -n 5 --graph
	echo "---------------------------------------------"
	git branch -D $GITHUB_BRANCH || true
	git checkout $GITHUB_COMMIT_ACTUAL -b $GITHUB_BRANCH || true
	git branch -v
fi
echo ""
echo ""
echo ""
echo "Git Revision"
echo "---------------------------------------------"
git status
echo "---------------------------------------------"
git describe
echo "============================================="
GIT_REVISION=$(git describe)

echo ""
echo ""
echo ""
echo "- Disk space free (after fixing git)"
echo "---------------------------------------------"
df -h
echo ""
DF_AFTER_GIT="$(($(stat -f --format="%a*%S" .)))"
awk "BEGIN {printf \"Git is using %.2f megabytes\n\",($DF_BEFORE_GIT-$DF_AFTER_GIT)/1024/1024}"
