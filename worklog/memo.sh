memo() {
	local f=~/infra-notes/notes/inbox.md
	mkdir -p "$(dirname "$f")"
	echo "- $(date '+%Y-%m-%d %H:%M') $*" >> "$f"
}

