"""Browser-side scrolling helpers for the Streamlit chat surface."""

AUTO_SCROLL_SCRIPT = """
<script>
(() => {
  const parentDocument = window.parent.document;
  const main = parentDocument.querySelector('[data-testid="stMain"]');

  const scrollToLatestMessage = () => {
    const messages = parentDocument.querySelectorAll('[data-testid="stChatMessage"]');
    const latestMessage = messages[messages.length - 1];
    latestMessage?.scrollIntoView({ behavior: "smooth", block: "end" });
    main?.scrollTo({ top: main.scrollHeight, behavior: "smooth" });
  };

  requestAnimationFrame(scrollToLatestMessage);
  window.setTimeout(scrollToLatestMessage, 80);
  window.setTimeout(scrollToLatestMessage, 260);
})();
</script>
"""
