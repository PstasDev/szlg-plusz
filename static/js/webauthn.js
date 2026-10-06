(() => {
  const csrfToken = () =>
    document.cookie
      .split("; ")
      .find((cookie) => cookie.startsWith("csrftoken="))
      ?.split("=")
      .slice(1)
      .join("=") ?? "";

  const decode = (value) => {
    const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  };

  const encode = (value) =>
    btoa(String.fromCharCode(...new Uint8Array(value)))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/g, "");

  const post = async (url, body = {}) => {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "A kérés nem sikerült.");
    return result;
  };

  const showError = (error) => {
    const target = document.getElementById("passkey-error");
    if (target) {
      target.textContent = error.message || "A passkey művelet nem sikerült.";
      target.hidden = false;
    }
  };

  const prepareRequest = (options) => ({
    ...options,
    challenge: decode(options.challenge),
    ...(options.allowCredentials
      ? {
          allowCredentials: options.allowCredentials.map((item) => ({
            ...item,
            id: decode(item.id),
          })),
        }
      : {}),
  });

  const serializeCredential = (credential) => {
    const response = {
      clientDataJSON: encode(credential.response.clientDataJSON),
    };
    if (credential.response.attestationObject) {
      response.attestationObject = encode(credential.response.attestationObject);
      response.transports = credential.response.getTransports?.() ?? [];
    } else {
      response.authenticatorData = encode(credential.response.authenticatorData);
      response.signature = encode(credential.response.signature);
      response.userHandle = credential.response.userHandle
        ? encode(credential.response.userHandle)
        : null;
    }
    return {
      id: credential.id,
      rawId: encode(credential.rawId),
      type: credential.type,
      response,
      clientExtensionResults: credential.getClientExtensionResults(),
      authenticatorAttachment: credential.authenticatorAttachment,
    };
  };

  const loginButton = document.getElementById("passkey-login");
  if (loginButton) {
    loginButton.addEventListener("click", async () => {
      loginButton.disabled = true;
      try {
        if (!window.PublicKeyCredential) throw new Error("Ez a böngésző nem támogatja a passkey-t.");
        const email = document.getElementById("passkey-email").value;
        const { options, challenge_id: challengeId } = await post(
          "/login/passkey/options/",
          { email },
        );
        const credential = await navigator.credentials.get({
          publicKey: prepareRequest(options),
        });
        if (!credential) throw new Error("A passkey azonosítás megszakadt.");
        const result = await post("/login/passkey/verify/", {
          challenge_id: challengeId,
          credential: serializeCredential(credential),
          next: new URLSearchParams(window.location.search).get("next") || "",
        });
        window.location.assign(result.redirect);
      } catch (error) {
        showError(error);
      } finally {
        loginButton.disabled = false;
      }
    });
  }

  const registerButton = document.getElementById("passkey-register");
  if (registerButton) {
    registerButton.addEventListener("click", async () => {
      registerButton.disabled = true;
      try {
        if (!window.PublicKeyCredential) throw new Error("Ez a böngésző nem támogatja a passkey-t.");
        const options = await post("/account/passkeys/register/options/");
        options.challenge = decode(options.challenge);
        options.user.id = decode(options.user.id);
        if (options.excludeCredentials) {
          options.excludeCredentials = options.excludeCredentials.map((item) => ({
            ...item,
            id: decode(item.id),
          }));
        }
        const credential = await navigator.credentials.create({ publicKey: options });
        if (!credential) throw new Error("A passkey regisztráció megszakadt.");
        const result = await post("/account/passkeys/register/verify/", {
          credential: serializeCredential(credential),
          name: document.getElementById("passkey-name").value,
        });
        window.location.assign(result.redirect);
      } catch (error) {
        showError(error);
      } finally {
        registerButton.disabled = false;
      }
    });
  }
})();
