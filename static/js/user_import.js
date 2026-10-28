(() => {
  const form = document.getElementById("user-import-form");
  if (!form) return;

  const textarea = document.getElementById("user-import-json");
  const previewButton = document.getElementById("user-import-preview-button");
  const message = document.getElementById("user-import-message");
  const preview = document.getElementById("user-import-preview");
  const summary = document.getElementById("user-import-summary");
  const invalidNote = document.getElementById("user-import-invalid-note");
  const rowsContainer = document.getElementById("user-import-rows");
  const startButton = document.getElementById("user-import-start");
  const progressPanel = document.getElementById("user-import-progress");
  const progressTitle = document.getElementById("user-import-progress-title");
  const progressLabel = document.getElementById("user-import-progress-label");
  const progressBar = document.getElementById("user-import-progress-bar");
  const sourceCheckboxes = Array.from(document.querySelectorAll(".user-import-source"));
  const sourceSummary = document.getElementById("user-import-sources-summary");
  const tagBulk = document.getElementById("user-import-tagozat-bulk");
  const bulkTagSelect = document.getElementById("user-import-bulk-tagozat");
  const assignTagButton = document.getElementById("user-import-assign-tagozat");
  const selectUnassignedButton = document.getElementById("user-import-select-unassigned");
  const selectAllCheckbox = document.getElementById("user-import-select-all");
  const tagMessage = document.getElementById("user-import-tagozat-message");
  const maxImportSources = Number(form.dataset.maxImportSources || 20);
  const csrfToken = form.querySelector("[name=csrfmiddlewaretoken]").value;

  let records = [];
  let sourceAppIds = [];
  let importing = false;

  function showMessage(text, isSuccess = false) {
    message.textContent = text;
    message.classList.toggle("success", isSuccess);
    message.hidden = !text;
  }

  function clearPreview() {
    if (importing) return;
    records = [];
    preview.hidden = true;
    progressPanel.hidden = true;
    rowsContainer.replaceChildren();
    sourceSummary.textContent = "";
    tagBulk.hidden = true;
    tagMessage.textContent = "";
    tagMessage.hidden = true;
    selectAllCheckbox.checked = false;
    selectAllCheckbox.disabled = true;
    startButton.disabled = true;
    showMessage("");
  }

  function addCell(row, text, className = "") {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = text || "–";
    row.append(cell);
    return cell;
  }

  function setRowStatus(record, state, label, detail) {
    const row = record.rowElement;
    const statusCell = row.querySelector(".row-status");
    statusCell.dataset.state = state;
    statusCell.textContent = label;
    row.querySelector(".row-detail").textContent = detail || "";
  }

  function showTagMessage(text, isSuccess = false) {
    tagMessage.textContent = text;
    tagMessage.classList.toggle("success", isSuccess);
    tagMessage.hidden = !text;
  }

  function updateTagAssignmentUI() {
    const unassigned = records.filter((record) => record.status !== "invalid" && record.needs_tagozat);
    tagBulk.hidden = unassigned.length === 0;
    selectAllCheckbox.disabled = unassigned.length === 0;

    const validCount = records.filter((record) => record.status !== "invalid").length;
    startButton.disabled = validCount === 0;
    selectAllCheckbox.checked = unassigned.length > 0 && unassigned.every(
      (record) => record.assignmentCheckbox?.checked,
    );
    const help = document.getElementById("user-import-tagozat-help");
    if (help && unassigned.length) {
      help.textContent = `${unassigned.length} diáknál nem ismert a tagozat. Jelölj ki több diákot, majd rendeld hozzájuk egyszerre a megfelelő tagozatot.`;
    }
  }

  function buildPreviewRows(apiRows) {
    rowsContainer.replaceChildren();
    records = apiRows;
    const statusLabels = { new: "Új fiók", existing: "Már létezik", invalid: "Hibás – kimarad" };

    for (const record of records) {
      const row = document.createElement("tr");
      const selectCell = document.createElement("td");
      if (record.needs_tagozat && record.status !== "invalid") {
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "tag-assignment-checkbox";
        checkbox.setAttribute("aria-label", `Tagozatot választok ehhez: ${record.email}`);
        checkbox.addEventListener("change", updateTagAssignmentUI);
        record.assignmentCheckbox = checkbox;
        selectCell.append(checkbox);
      }
      row.append(selectCell);
      addCell(row, String(record.index));
      addCell(row, record.email);
      addCell(row, record.display_name);
      let classLabel = record.class_label || "";
      if (record.class_inferred && classLabel) classLabel += " (e-mailből)";
      addCell(row, classLabel);
      const tagCell = addCell(
        row,
        record.tagozat_label || (record.needs_tagozat ? "Hiányzik (üresen hagyható)" : ""),
        "row-tagozat",
      );
      record.tagozatCell = tagCell;
      const status = addCell(row, statusLabels[record.status] || "Ellenőrizve", "row-status");
      status.dataset.state = record.status;
      const previewDetails = [...(record.errors || []), ...(record.warnings || [])];
      const detail = addCell(row, previewDetails.join(" "), "row-detail");
      record.rowElement = row;
      rowsContainer.append(row);
      if (!previewDetails.length) detail.textContent = "E-mail alapján ellenőrizve.";
    }
    updateTagAssignmentUI();
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify(payload),
    });

    const isJson = response.headers.get("Content-Type")?.includes("application/json");
    let data = {};
    if (isJson) {
      try {
        data = await response.json();
      } catch (_error) {
        data = {};
      }
    }
    if (!isJson || response.redirected) {
      const error = new Error("A munkamenet lejárt vagy a szerver nem JSON-választ adott. Frissítsd az oldalt, majd próbáld újra.");
      error.status = response.redirected ? 401 : response.status;
      throw error;
    }
    if (!response.ok) {
      const details = Array.isArray(data.details) ? ` ${data.details.join(" ")}` : "";
      const error = new Error((data.error || "A kérés nem sikerült.") + details);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (importing) return;
    clearPreview();

    let payload;
    try {
      payload = JSON.parse(textarea.value);
    } catch (_error) {
      showMessage("A beillesztett szöveg nem érvényes JSON. Ellenőrizd a vesszőket és az idézőjeleket.");
      textarea.focus();
      return;
    }

    sourceAppIds = sourceCheckboxes
      .filter((checkbox) => checkbox.checked)
      .map((checkbox) => Number(checkbox.value));
    if (!sourceAppIds.length) {
      showMessage("Válaszd ki, melyik alkalmazás(ok) adatbázisából származik az import.");
      sourceCheckboxes[0]?.focus();
      return;
    }
    if (sourceAppIds.length > maxImportSources) {
      showMessage(`Legfeljebb ${maxImportSources} forrásalkalmazást választhatsz ki.`);
      return;
    }

    previewButton.disabled = true;
    textarea.disabled = true;
    sourceCheckboxes.forEach((checkbox) => { checkbox.disabled = true; });
    showMessage("A rekordokat ellenőrizzük…");
    try {
      const result = await postJson(form.dataset.previewUrl, {
        users: payload,
        source_app_ids: sourceAppIds,
      });
      buildPreviewRows(result.rows);
      const { new: newCount, existing: existingCount, invalid: invalidCount } = result.counts;
      summary.textContent = `${newCount} új fiók, ${existingCount} már létező fiók, ${invalidCount} hibás rekord.`;
      sourceSummary.textContent = `Forrásalkalmazás(ok): ${(result.source_apps || []).join(", ")}`;
      invalidNote.hidden = invalidCount === 0;
      preview.hidden = false;
      progressPanel.hidden = true;
      showMessage("Az ellenőrzés kész. Az adatbázis még nem változott.", true);
    } catch (error) {
      showMessage(error.message);
    } finally {
      previewButton.disabled = false;
      textarea.disabled = false;
      sourceCheckboxes.forEach((checkbox) => { checkbox.disabled = false; });
    }
  });

  startButton.addEventListener("click", async () => {
    const validRecords = records.filter((record) => record.status !== "invalid");
    if (!validRecords.length || importing) return;

    importing = true;
    startButton.disabled = true;
    previewButton.disabled = true;
    textarea.disabled = true;
    sourceCheckboxes.forEach((checkbox) => { checkbox.disabled = true; });
    progressPanel.hidden = false;
    progressTitle.textContent = "Importálás folyamatban";
    progressBar.max = validRecords.length;
    progressBar.value = 0;
    showMessage("");

    let created = 0;
    let updated = 0;
    let unchanged = 0;
    let failed = 0;
    let completed = 0;
    let stopped = false;

    for (const record of validRecords) {
      setRowStatus(record, "working", "Folyamatban…", "A fiókot az e-mail-cím alapján újra ellenőrizzük.");
      progressLabel.textContent = `Feldolgozás: ${completed + 1} / ${validRecords.length}`;
      try {
        const result = await postJson(form.dataset.importUrl, {
          user: record.data,
          source_app_ids: sourceAppIds,
        });
        if (!["created", "updated", "unchanged"].includes(result.status)) {
          throw new Error("A szerver válasza nem tartalmaz importeredményt. Ellenőrizd a rekordot.");
        }
        if (result.status === "created") created += 1;
        else if (result.status === "updated") updated += 1;
        else unchanged += 1;

        const details = [result.message];
        if (result.added?.length) details.push(`Kitöltve: ${result.added.join(", ")}.`);
        if (result.preserved?.length) details.push(`Változatlanul hagyva: ${result.preserved.join(", ")}.`);
        if (result.sources_added?.length) details.push(`Forrásként rögzítve: ${result.sources_added.join(", ")}.`);
        if (result.warnings?.length) details.push(...result.warnings);
        const labels = { created: "Létrehozva", updated: "Kiegészítve", unchanged: "Változatlan" };
        setRowStatus(record, result.status, labels[result.status] || "Kész", details.join(" "));
      } catch (error) {
        failed += 1;
        setRowStatus(record, "error", "Hiba", error.message);
        if (error.status === 401 || error.status === 403) {
          const pendingRecords = validRecords.slice(completed + 1);
          failed += pendingRecords.length;
          for (const pending of pendingRecords) {
            setRowStatus(pending, "error", "Megszakítva", "A további rekordok nem kerültek feldolgozásra.");
          }
          completed += 1;
          progressBar.value = completed;
          stopped = true;
          break;
        }
      }

      completed += 1;
      progressBar.value = completed;
      progressLabel.textContent = `Feldolgozva: ${completed} / ${validRecords.length}`;
    }

    const successCount = created + updated + unchanged;
    summary.textContent = `Import kész: ${created} új fiók, ${updated} kiegészített, ${unchanged} változatlan, ${failed} hibás.`;
    if (failed) showMessage("Az import részben sikerült. A hibás rekordok részlete a táblázatban látható.");
    else showMessage("Minden érvényes rekord importálása befejeződött.", true);
    progressLabel.textContent = stopped
      ? `Megszakadt: ${successCount} sikeres, ${failed} hibás vagy feldolgozatlan rekord.`
      : `Befejezve: ${successCount} sikeres, ${failed} hibás rekord.`;
    progressTitle.textContent = stopped ? "Importálás megszakadt" : "Importálás kész";
    importing = false;
    textarea.disabled = false;
    previewButton.disabled = false;
    sourceCheckboxes.forEach((checkbox) => { checkbox.disabled = false; });
  });

  selectAllCheckbox.addEventListener("change", () => {
    for (const record of records) {
      if (record.needs_tagozat && record.assignmentCheckbox) {
        record.assignmentCheckbox.checked = selectAllCheckbox.checked;
      }
    }
    updateTagAssignmentUI();
  });

  selectUnassignedButton.addEventListener("click", () => {
    for (const record of records) {
      if (record.needs_tagozat && record.assignmentCheckbox) {
        record.assignmentCheckbox.checked = true;
      }
    }
    updateTagAssignmentUI();
  });

  assignTagButton.addEventListener("click", () => {
    const slug = bulkTagSelect.value;
    const selectedRecords = records.filter(
      (record) => record.needs_tagozat && record.assignmentCheckbox?.checked,
    );
    if (!slug) {
      showTagMessage("Válassz tagozatot a hozzárendeléshez.");
      return;
    }
    if (!selectedRecords.length) {
      showTagMessage("Jelölj ki legalább egy diákot.");
      return;
    }

    const tagozatName = bulkTagSelect.selectedOptions[0].textContent.trim();
    for (const record of selectedRecords) {
      record.data.tagozat = slug;
      record.needs_tagozat = false;
      record.tagozat_label = tagozatName;
      record.tagozatCell.textContent = tagozatName;
      record.assignmentCheckbox.checked = false;
      record.assignmentCheckbox.disabled = true;
    }
    showTagMessage(`${selectedRecords.length} diákhoz rendeltük hozzá: ${tagozatName}.`, true);
    updateTagAssignmentUI();
  });

  textarea.addEventListener("input", clearPreview);
  sourceCheckboxes.forEach((checkbox) => checkbox.addEventListener("change", clearPreview));
})();
