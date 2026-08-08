(function () {
  "use strict";
  const params = new URLSearchParams(window.location.search);
  const agentId = params.get("agentId");
  const statusEl = document.getElementById("status");
  const feedEl = document.getElementById("feed");
  const metaEl = document.getElementById("agent-meta");

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "status" + (cls ? " " + cls : "");
  }

  function renderPosts(posts) {
    if (!posts || posts.length === 0) {
      feedEl.innerHTML = "";
      setStatus("No posts yet. The agent will publish when it finds something worth saying.", "empty");
      return;
    }
    setStatus("Latest posts", "");
    feedEl.innerHTML = posts.map(function (post) {
      return "<li><h3>" + post.title + "</h3><p>" + post.body + "</p></li>";
    }).join("");
  }

  async function loadFeed() {
    if (!agentId) {
      setStatus("Missing agentId in the query string.", "error");
      return;
    }
    metaEl.textContent = "Agent: " + agentId;
    try {
      const response = await fetch("/api/agent/feed?agentId=" + encodeURIComponent(agentId) + "&limit=20");
      if (!response.ok) {
        throw new Error("request failed");
      }
      const payload = await response.json();
      renderPosts(payload.posts || []);
    } catch (error) {
      setStatus("Unable to load feed right now.", "error");
    }
  }

  loadFeed();
})();
