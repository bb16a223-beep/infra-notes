# worklog: コマンド履歴に日時を残し、実行のたびにすぐファイルへ書き出す
# ~/.bashrc の末尾から読み込む想定（既存の HISTSIZE などを上書きする）

HISTTIMEFORMAT='%F %T '
HISTSIZE=100000
HISTFILESIZE=200000
shopt -s histappend

case ";${PROMPT_COMMAND:-};" in
  *"history -a"*) ;;
  *) PROMPT_COMMAND="history -a${PROMPT_COMMAND:+; $PROMPT_COMMAND}" ;;
esac
