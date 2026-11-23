"use strict";

const loginView = document.getElementById("login-view");
const chatView = document.getElementById("chat-view");
const loginForm = document.getElementById("login-form");
const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message");
const messages = document.getElementById("messages");
const status = document.getElementById("status");
const loginError = document.getElementById("login-error");
let csrfToken = "";
let busy = false;

async function request(path, options = {}) {
  const response = await fetch(path, {credentials: "same-origin", cache: "no-store", ...options});
  if (response.status === 204) return null;
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Request failed.");
  return payload;
}

function showError(element, error) {
  element.textContent = error.message || "Something went wrong. Please try again.";
  element.hidden = false;
}

function addMessage(role, text) {
  document.getElementById("welcome").hidden = true;
  const bubble = document.createElement("div");
  bubble.className = `message ${role === "user" ? "user" : "assistant"}`;
  bubble.textContent = text; // Never interpret model or user content as HTML.
  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;
}

async function showChat(session) {
  csrfToken = session.csrf_token;
  loginView.hidden = true;
  chatView.hidden = false;
  document.getElementById("logout-button").hidden = !session.can_logout;
  document.getElementById("provider-label").textContent = session.provider || "Support assistant";
  const history = await request("api/history");
  messages.querySelectorAll(".message").forEach((item) => item.remove());
  document.getElementById("welcome").hidden = history.messages.length > 0;
  for (const item of history.messages) addMessage(item.role, item.content);
  messageInput.focus();
}

async function initialize() {
  try {
    const session = await request("api/session");
    csrfToken = session.csrf_token;
    if (session.authenticated) await showChat(session);
    else { loginView.hidden = false; chatView.hidden = true; }
  } catch (error) {
    loginView.hidden = false;
    showError(loginError, error);
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  const button = loginForm.querySelector("button");
  button.disabled = true;
  try {
    const session = await request("login", {
      method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
      body: JSON.stringify({username: document.getElementById("username").value, password: document.getElementById("password").value}),
    });
    loginForm.reset();
    await showChat(session);
  } catch (error) { showError(loginError, error); }
  finally { button.disabled = false; }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const message = messageInput.value.trim();
  if (!message) return;
  busy = true;
  document.getElementById("send-button").disabled = true;
  status.textContent = "Working on your question…";
  addMessage("user", message);
  messageInput.value = "";
  try {
    const result = await request("api/chat", {
      method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
      body: JSON.stringify({message}),
    });
    addMessage("assistant", result.response);
    status.textContent = "";
  } catch (error) { status.textContent = error.message || "Request failed."; }
  finally { busy = false; document.getElementById("send-button").disabled = false; messageInput.focus(); }
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

document.querySelectorAll(".example").forEach((button) => button.addEventListener("click", () => {
  messageInput.value = button.dataset.prompt;
  messageInput.focus();
}));

document.getElementById("clear-button").addEventListener("click", async () => {
  if (busy) return;
  try {
    await request("api/reset", {method: "POST", headers: {"X-CSRF-Token": csrfToken}});
    messages.querySelectorAll(".message").forEach((item) => item.remove());
    document.getElementById("welcome").hidden = false;
    status.textContent = "Conversation cleared.";
  } catch (error) { status.textContent = error.message || "Could not clear chat."; }
});

document.getElementById("logout-button").addEventListener("click", async () => {
  try { await request("logout", {method: "POST", headers: {"X-CSRF-Token": csrfToken}}); }
  finally { location.reload(); }
});

initialize();
