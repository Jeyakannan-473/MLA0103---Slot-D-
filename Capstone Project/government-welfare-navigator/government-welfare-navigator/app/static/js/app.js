document.addEventListener("DOMContentLoaded", function () {
  if (window.lucide) { lucide.createIcons({ attrs: { class: "icon" } }); }

  // Bootstrap validation + loading state on submit
  document.querySelectorAll("form.needs-validation").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!form.checkValidity()) { e.preventDefault(); e.stopPropagation(); }
      else {
        var b = form.querySelector("[data-loading]");
        if (b) { b.classList.add("is-loading"); b.setAttribute("aria-busy", "true"); }
      }
      form.classList.add("was-validated");
    });
  });

  // Confirm dangerous actions
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
  });

  // Assistant chat
  var box = document.getElementById("chat-box");
  if (box) {
    var form = document.getElementById("chat-form"), input = document.getElementById("chat-input");
    var convId = null, token = document.querySelector('meta[name="csrf-token"]').content;
    function add(text, who, sources) {
      var d = document.createElement("div"); d.className = "msg " + who; d.textContent = text;
      (sources || []).forEach(function (s) {
        var a = document.createElement("a"); a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer";
        a.className = "src"; a.textContent = "Source: " + s.title; d.appendChild(a);
      });
      box.appendChild(d); box.scrollTop = box.scrollHeight; return d;
    }
    function send(text) {
      if (!text.trim()) return;
      add(text, "user"); input.value = "";
      var wait = add("Looking this up in the scheme database…", "bot");
      fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": token },
        body: JSON.stringify({ message: text, conversation_id: convId }) })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          wait.remove();
          if (!res.ok) { add(res.j.error || "Sorry, something went wrong.", "bot"); return; }
          convId = res.j.conversation_id; add(res.j.reply, "bot", res.j.sources);
        })
        .catch(function () { wait.remove(); add("Network error. Please try again.", "bot"); });
    }
    form.addEventListener("submit", function (e) { e.preventDefault(); send(input.value); });
    document.querySelectorAll("[data-ask]").forEach(function (b) { b.addEventListener("click", function () { send(b.dataset.ask); }); });
  }
});
