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

  // Browsers report "already registered here" and "cancelled" with generic DOM errors.
  const friendlyMessage = (error) => {
    if (error?.name === "InvalidStateError") {
      return "Ezen az eszközön már van jelkulcsod ehhez a fiókhoz.";
    }
    if (error?.name === "NotAllowedError") {
      return "A jelkulcs használata megszakadt, vagy lejárt az idő.";
    }
    return error?.message || "A jelkulcs-művelet nem sikerült.";
  };

  const showError = (error) => {
    const target = document.getElementById("passkey-error");
    if (target) {
      target.textContent = friendlyMessage(error);
      target.hidden = false;
    }
  };

  // A readable name such as "Chrome · Windows", so users are never asked for one.
  const deviceName = () => {
    const ua = navigator.userAgent || "";
    const hinted = navigator.userAgentData?.platform || "";
    const platforms = [
      [/iPhone/, "iPhone"],
      [/iPad/, "iPad"],
      [/Android/, "Android"],
      [/Windows/, "Windows"],
      [/Mac OS X|Macintosh/, "Mac"],
      [/CrOS/, "ChromeOS"],
      [/Linux/, "Linux"],
    ];
    const os = platforms.find(([pattern]) => pattern.test(ua))?.[1] || hinted;
    const browsers = [
      [/Edg\//, "Edge"],
      [/OPR\/|Opera/, "Opera"],
      [/SamsungBrowser/, "Samsung Internet"],
      [/Firefox\/|FxiOS/, "Firefox"],
      [/Chrome\/|CriOS/, "Chrome"],
      [/Safari\//, "Safari"],
    ];
    const browser = browsers.find(([pattern]) => pattern.test(ua))?.[1] || "";
    return [browser, os].filter(Boolean).join(" · ") || "Saját eszköz";
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
        if (!window.PublicKeyCredential) throw new Error("Ez a böngésző nem támogatja a jelkulcsot.");
        const emailInput = document.getElementById("passkey-email");
        const email = emailInput ? emailInput.value : "";
        const { options, challenge_id: challengeId } = await post(
          "/login/passkey/options/",
          { email },
        );
        const credential = await navigator.credentials.get({
          publicKey: prepareRequest(options),
        });
        if (!credential) throw new Error("A jelkulcsos azonosítás megszakadt.");
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
        if (!window.PublicKeyCredential) throw new Error("Ez a böngésző nem támogatja a jelkulcsot.");
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
        if (!credential) throw new Error("A jelkulcs regisztrációja megszakadt.");
        const nameInput = document.getElementById("passkey-name");
        const name = (nameInput && nameInput.value.trim()) || deviceName();
        const result = await post("/account/passkeys/register/verify/", {
          credential: serializeCredential(credential),
          name,
          promo: registerButton.dataset.promo === "1",
        });
        window.location.assign(result.redirect);
      } catch (error) {
        if (error?.name === "InvalidStateError" && registerButton.dataset.promo === "1") {
          // The account's credential already exists on this device: stop offering here.
          const form = document.getElementById("passkey-skip-form");
          if (form) {
            const flag = document.createElement("input");
            flag.type = "hidden";
            flag.name = "device_ready";
            flag.value = "1";
            form.appendChild(flag);
            form.submit();
            return;
          }
        }
        showError(error);
      } finally {
        registerButton.disabled = false;
      }
    });
  }

  // Jelkulcs offer shown after a password login.
  const promoScreen = document.querySelector("[data-promo-screen]");
  if (promoScreen) {
    const label = document.getElementById("device-name");
    if (label) label.textContent = deviceName();

    // Devices that cannot use a jelkulcs skip the offer without a visible detour.
    const skip = () => document.getElementById("passkey-skip-form")?.submit();
    const available = window.PublicKeyCredential?.isUserVerifyingPlatformAuthenticatorAvailable;
    if (!available) {
      skip();
    } else {
      window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()
        .then((supported) => { if (!supported) skip(); })
        .catch(skip);
    }
  }
})();
