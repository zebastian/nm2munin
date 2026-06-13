# render-lib.sh -- sourced helper. Expand @TOKEN@ placeholders in a template
# from the current environment. Tokens are auto-discovered from the template,
# so this works for any set of variables (manager configs, example ION configs,
# future topologies) without a hardcoded list.
#
#   render_file <template> <dest>
#
# Fails if the template references a token that is unset in the environment.

render_file() {
    local src="$1" dst="$2" tok val expr=""
    local toks
    toks=$(grep -oE '@[A-Z_][A-Z0-9_]*@' "$src" | sort -u | tr -d '@')
    for tok in $toks; do
        if [ -z "${!tok+set}" ]; then
            echo "render: $src references @${tok}@ but it is unset" >&2
            return 1
        fi
        val=${!tok}
        # escape characters significant to the sed s|...|...| expression
        val=${val//\\/\\\\}; val=${val//|/\\|}; val=${val//&/\\&}
        expr+="s|@${tok}@|${val}|g;"
    done
    sed "${expr:-}" "$src" > "$dst"
}
