export default function QuickReplies({ replies = [], onSelect, disabled }) {
  if (!replies || replies.length === 0) return null

  return (
    <div className="llm-quick-replies">
      {replies.map((reply, idx) => (
        <button
          key={idx}
          onClick={() => onSelect(reply)}
          disabled={disabled}
          className="quick-reply-chip"
        >
          {reply}
        </button>
      ))}
    </div>
  )
}
