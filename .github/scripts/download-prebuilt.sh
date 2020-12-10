#!/bin/bash

# Script to clone prebuilt repo to copy results into.
GITHUB_PR_NUMBER = $(echo $GITHUB_REF | awk 'BEGIN { FS = "/" } ; { print $3 }')

if [ ! -z "$GITHUB_ACTIONS" -a "$GITHUB_ACTIONS" = "true" ]; then
	# Don't clone prebuilt on a pull request.
	if [ ! -z "$GITHUB_PR_NUMBER" -a "$GITHUB_PR_NUMBER" != "false" ]; then
		echo ""
		echo ""
		echo ""
		echo "- Pull request, so no prebuilt pushing."

	# Don't clone if no github authentication
	elif [ -z "$GH_TOKEN" ]; then
		echo ""
		echo ""
		echo ""
		echo "- No Github token (GH_TOKEN) so unable to push built files"

	# Don't clone if we don't know which branch we are on
	elif [ -z "$GITHUB_BRANCH" ]; then
		echo ""
		echo ""
		echo ""
		echo "- No branch name (\$GITHUB_BRANCH), unable to copy built files"

	# Don't clone if we don't know which repo we are using
	elif [ -z "$GITHUB_REPOSITORY" ]; then
		echo ""
		echo ""
		echo ""
		echo "- No repo slug name (\$GITHUB_REPOSITORY), unable to copy built files"

	else
		# Look at repo we are running in to determine where to try pushing to if in a fork
		PREBUILT_REPO=HDMI2USB-firmware-prebuilt
		PREBUILT_REPO_OWNER=$(echo $GITHUB_REPOSITORY|awk -F'/' '{print $1}')
	fi
fi


if [ -z "$PREBUILT_DIR" ]; then
	echo ""
	echo ""
	echo ""
	echo "- No PREBUILT_DIR value found."

elif [ -z "$PREBUILT_REPO" ]; then
	echo ""
	echo ""
	echo ""
	echo "- No PREBUILT_REPO value found."

elif [ -z "$PREBUILT_REPO_OWNER" ]; then
	echo ""
	echo ""
	echo ""
	echo "- No PREBUILT_REPO_OWNER value found."

else
	echo ""
	echo ""
	echo ""
	echo "- Download built files from github.com/$PREBUILT_REPO_OWNER/$PREBUILT_REPO (to upload results)"
	echo "---------------------------------------------"
	(
		# Do a sparse, shallow checkout to keep disk space usage down.
		#mkdir -p $PREBUILT_DIR
		svn co --depth immediates https://github.com/$PREBUILT_REPO_OWNER/$PREBUILT_REPO/trunk/ $PREBUILT_DIR
		cd $PREBUILT_DIR
		SVN_REVISION=$(svnversion | sed -e's/P$//')

		for I in *; do
			if [ "$I" == "archive" ]; then
				continue
			fi
			svn update -r$SVN_REVISION --set-depth infinity $I
		done
		svn update -r$SVN_REVISION --set-depth immediates archive/$GITHUB_BRANCH/
		echo ""
		PREBUILT_DIR_DU=$(du -h -s . | sed -e's/[ \t]*\.$//')
		echo "Prebuilt repo checkout is using $PREBUILT_DIR_DU"
		ls -l $PWD
		ls -l $PREBUILT_DIR/archive
	)
	echo "============================================="
fi
