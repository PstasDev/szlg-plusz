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
  let validating = false;
  let nextRecordId = 1;

  function showMessage(text, isSuccess = false) {
    message.textContent = text;
    message.classList.toggle("success", isSuccess);
    message.hidden = !text;
  }

  function clearPreview() {
    if (importing || validating) return;
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
    const unassigned = records.filter(
      (record) => !record.excluded && record.status !== "invalid" && record.needs_tagozat,
    );
    tagBulk.hidden = unassigned.length === 0;
    selectAllCheckbox.disabled = unassigned.length === 0;
    selectAllCheckbox.checked = unassigned.length > 0 && unassigned.every(
      (record) => record.assignmentCheckbox?.checked,
    );
    const help = document.getElementById("user-import-tagozat-help");
    if (help && unassigned.length) {
      help.textContent = `${unassigned.length} diáknál nem ismert a tagozat. Jelölj ki több diákot, majd rendeld hozzájuk egyszerre a megfelelő tagozatot.`;
    }
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function rawRecord(record) {
    return record.rawData && typeof record.rawData === "object" && !Array.isArray(record.rawData)
      ? record.rawData
      : {};
  }

  function editorValue(record, key) {
    const raw = rawRecord(record);
    const normalized = record.data || {};
    if (key === "osztaly") {
      if (typeof raw.osztaly === "string" && raw.osztaly.trim()) return raw.osztaly;
      if (raw.kezdes_eve != null && raw.szekcio) return `${raw.kezdes_eve}${raw.szekcio}`;
      if (normalized.kezdes_eve != null && normalized.szekcio) {
        return `${normalized.kezdes_eve}${normalized.szekcio}`;
      }
      return "";
    }
    const value = raw[key] ?? normalized[key] ?? "";
    return typeof value === "string" ? value : String(value);
  }

  function makeEditorField(record, key, labelText, type = "text", maxLength = null) {
    const wrapper = document.createElement("div");
    wrapper.className = "import-edit-field";
    const id = `import-edit-${record.localId}-${key}`;
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = labelText;
    const input = document.createElement("input");
    input.id = id;
    input.name = key;
    input.type = type;
    input.value = editorValue(record, key);
    if (maxLength) input.maxLength = maxLength;
    wrapper.append(label, input);
    return { wrapper, input };
  }

  function makeEditorRow(record) {
    const editorRow = document.createElement("tr");
    editorRow.className = "import-editor-row";
    editorRow.hidden = true;
    const cell = document.createElement("td");
    cell.colSpan = 9;
    const editor = document.createElement("div");
    editor.className = "import-editor";
    const fields = document.createElement("div");
    fields.className = "import-editor-fields";
    const inputs = {};
    const definitions = [
      ["email", "E-mail-cím", "email", 254],
      ["last_name", "Vezetéknév", "text", 150],
      ["first_name", "Keresztnév", "text", 150],
      ["phone", "Telefonszám", "text", 32],
      ["date_of_birth", "Születési dátum", "date", null],
      ["osztaly", "Osztály (pl. 2023F vagy 10. F)", "text", 40],
      ["om_id", "OM azonosító", "text", 32],
      ["tagozat", "Tagozat neve vagy slugja", "text", 120],
      ["employee_number", "Munkatársi azonosító", "text", 32],
    ];
    for (const [key, label, type, maxLength] of definitions) {
      const field = makeEditorField(record, key, label, type, maxLength);
      inputs[key] = field.input;
      fields.append(field.wrapper);
    }
    editor.append(fields);

    const roleLabel = document.createElement("label");
    roleLabel.className = "import-editor-student";
    const studentCheckbox = document.createElement("input");
    studentCheckbox.type = "checkbox";
    studentCheckbox.checked = record.has_student_profile
      || (typeof rawRecord(record).is_student === "boolean"
        ? rawRecord(record).is_student
        : Boolean(record.is_student));
    studentCheckbox.addEventListener("change", () => {
      if (!studentCheckbox.checked) {
        inputs.osztaly.value = "";
        inputs.om_id.value = "";
        inputs.tagozat.value = "";
      }
    });
    const studentText = document.createElement("span");
    studentText.textContent = "Diákprofilként kezeljük";
    roleLabel.append(studentCheckbox, studentText);
    editor.append(roleLabel);

    const actions = document.createElement("div");
    actions.className = "import-editor-actions";
    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.className = "btn sm";
    saveButton.textContent = "Módosítások ellenőrzése";
    saveButton.addEventListener("click", async () => {
      if (importing || validating) return;
      const edited = {};
      for (const [key, input] of Object.entries(inputs)) {
        const value = input.value.trim();
        if (value) edited[key] = value;
      }
      edited.is_student = studentCheckbox.checked;
      const previous = record.rawData;
      record.rawData = edited;
      saveButton.disabled = true;
      try {
        await revalidateActiveRecords();
      } catch (_error) {
        record.rawData = previous;
        renderRows();
      } finally {
        saveButton.disabled = false;
      }
    });
    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.className = "btn text sm";
    cancelButton.textContent = "Mégse";
    cancelButton.addEventListener("click", () => {
      editorRow.hidden = true;
      if (record.editButton) record.editButton.textContent = "Szerkesztés";
    });
    actions.append(saveButton, cancelButton);
    editor.append(actions);
    cell.append(editor);
    editorRow.append(cell);
    return editorRow;
  }

  function makeActionButton(label, className, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function updatePreviewSummary() {
    const active = records.filter((record) => !record.excluded);
    const counts = {
      new: active.filter((record) => record.status === "new").length,
      existing: active.filter((record) => record.status === "existing").length,
      invalid: active.filter((record) => record.status === "invalid").length,
    };
    const skipped = records.length - active.length;
    summary.textContent = `${counts.new} új fiók, ${counts.existing} már létező fiók, ${counts.invalid} hibás rekord${skipped ? `, ${skipped} kihagyva` : ""}.`;
    invalidNote.hidden = counts.invalid === 0;
    startButton.disabled = importing || validating || counts.new + counts.existing === 0;
    startButton.textContent = `Importálás indítása (${counts.new + counts.existing} rekord)`;
    updateTagAssignmentUI();
  }

  function renderRows() {
    rowsContainer.replaceChildren();
    const statusLabels = { new: "Új fiók", existing: "Már létezik", invalid: "Hibás – kimarad" };

    records.forEach((record, index) => {
      const row = document.createElement("tr");
      if (record.excluded) row.classList.add("import-row-skipped");
      const selectCell = document.createElement("td");
      if (!record.excluded && record.needs_tagozat && record.status !== "invalid") {
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "tag-assignment-checkbox";
        checkbox.setAttribute("aria-label", `Tagozatot választok ehhez: ${record.email}`);
        checkbox.addEventListener("change", updateTagAssignmentUI);
        record.assignmentCheckbox = checkbox;
        selectCell.append(checkbox);
      } else {
        delete record.assignmentCheckbox;
      }
      row.append(selectCell);
      addCell(row, String(index + 1));
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
      const status = addCell(
        row,
        record.excluded ? "Kihagyva" : (statusLabels[record.status] || "Ellenőrizve"),
        "row-status",
      );
      status.dataset.state = record.excluded ? "excluded" : record.status;
      const previewDetails = record.excluded
        ? ["Ezt a sort nem importáljuk."]
        : [...(record.errors || []), ...(record.warnings || [])];
      const detail = addCell(row, previewDetails.join(" "), "row-detail");
      const actions = document.createElement("td");
      actions.className = "import-row-actions";
      record.rowElement = row;

      if (record.excluded) {
        actions.append(makeActionButton("Visszaállítás", "btn outline sm", async () => {
          if (importing || validating) return;
          record.excluded = false;
          try {
            await revalidateActiveRecords();
          } catch (_error) {
            record.excluded = true;
            renderRows();
          }
        }));
        row.append(actions);
        rowsContainer.append(row);
        return;
      }

      const editButton = makeActionButton("Szerkesztés", "btn outline sm", () => {
        if (importing || validating) return;
        if (!record.editorRow) {
          record.editorRow = makeEditorRow(record);
          row.after(record.editorRow);
        }
        record.editorRow.hidden = !record.editorRow.hidden;
        editButton.textContent = record.editorRow.hidden ? "Szerkesztés" : "Bezárás";
      });
      record.editButton = editButton;
      actions.append(
        editButton,
        makeActionButton("Kihagyás", "btn text sm", async () => {
          if (importing || validating) return;
          record.excluded = true;
          try {
            await revalidateActiveRecords();
          } catch (_error) {
            renderRows();
          }
        }),
      );
      row.append(actions);
      rowsContainer.append(row);
      if (!previewDetails.length) detail.textContent = "E-mail alapján ellenőrizve.";
    });

    updatePreviewSummary();
  }

  function buildPreviewRows(apiRows, rawUsers) {
    records = apiRows.map((record, index) => ({
      ...record,
      rawData: cloneJson(rawUsers[index]),
      excluded: false,
      localId: nextRecordId++,
    }));
    renderRows();
  }

  function setPreviewControlsBusy(busy) {
    preview.querySelectorAll("button, input, select").forEach((element) => {
      if (element.id === "user-import-start") return;
      if (busy) {
        element.dataset.wasDisabled = element.disabled ? "1" : "0";
        element.disabled = true;
      } else {
        element.disabled = element.dataset.wasDisabled === "1";
        delete element.dataset.wasDisabled;
      }
    });
  }

  async function revalidateActiveRecords() {
    if (importing || validating) return;
    const active = records.filter((record) => !record.excluded);
    if (!active.length) {
      renderRows();
      return;
    }

    validating = true;
    previewButton.disabled = true;
    textarea.disabled = true;
    sourceCheckboxes.forEach((checkbox) => { checkbox.disabled = true; });
    setPreviewControlsBusy(true);
    showMessage("A módosított rekordokat újraellenőrizzük…");
    try {
      const result = await postJson(form.dataset.previewUrl, {
        users: active.map((record) => record.rawData),
        source_app_ids: sourceAppIds,
      });
      result.rows.forEach((newRecord, index) => {
        const oldRecord = active[index];
        const rawData = oldRecord.rawData;
        const localId = oldRecord.localId;
        Object.assign(oldRecord, newRecord, { rawData, localId, excluded: false });
        delete oldRecord.rowElement;
        delete oldRecord.editorRow;
        delete oldRecord.assignmentCheckbox;
        delete oldRecord.tagozatCell;
        delete oldRecord.editButton;
      });
      sourceSummary.textContent = `Forrásalkalmazás(ok): ${(result.source_apps || []).join(", ")}`;
      preview.hidden = false;
      renderRows();
      showMessage("Az előnézet frissült. Az adatbázis még nem változott.", true);
    } catch (error) {
      showMessage(error.message);
      throw error;
    } finally {
      validating = false;
      previewButton.disabled = false;
      textarea.disabled = false;
      sourceCheckboxes.forEach((checkbox) => { checkbox.disabled = false; });
      setPreviewControlsBusy(false);
      updatePreviewSummary();
    }
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
    if (importing || validating) return;
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
      sourceSummary.textContent = `Forrásalkalmazás(ok): ${(result.source_apps || []).join(", ")}`;
      preview.hidden = false;
      progressPanel.hidden = true;
      buildPreviewRows(result.rows, payload);
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
    const activeRecords = records.filter((record) => !record.excluded);
    const validRecords = activeRecords.filter((record) => record.status !== "invalid");
    if (!validRecords.length || importing || validating) return;

    importing = true;
    startButton.disabled = true;
    previewButton.disabled = true;
    textarea.disabled = true;
    sourceCheckboxes.forEach((checkbox) => { checkbox.disabled = true; });
    setPreviewControlsBusy(true);
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
    const invalidCount = activeRecords.filter((record) => record.status === "invalid").length;
    const skippedCount = records.filter((record) => record.excluded).length;
    summary.textContent = `Import kész: ${created} új fiók, ${updated} kiegészített, ${unchanged} változatlan, ${failed} mentési hiba, ${invalidCount} hibás rekord kihagyva, ${skippedCount} kézzel kihagyva.`;
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
    setPreviewControlsBusy(false);
    startButton.disabled = true;
  });

  selectAllCheckbox.addEventListener("change", () => {
    for (const record of records) {
      if (!record.excluded && record.status !== "invalid" && record.needs_tagozat && record.assignmentCheckbox) {
        record.assignmentCheckbox.checked = selectAllCheckbox.checked;
      }
    }
    updateTagAssignmentUI();
  });

  selectUnassignedButton.addEventListener("click", () => {
    for (const record of records) {
      if (!record.excluded && record.status !== "invalid" && record.needs_tagozat && record.assignmentCheckbox) {
        record.assignmentCheckbox.checked = true;
      }
    }
    updateTagAssignmentUI();
  });

  assignTagButton.addEventListener("click", () => {
    const slug = bulkTagSelect.value;
    const selectedRecords = records.filter(
      (record) => !record.excluded && record.needs_tagozat && record.assignmentCheckbox?.checked,
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
      record.data.is_student = true;
      record.rawData = { ...rawRecord(record), tagozat: slug, is_student: true };
      record.needs_tagozat = false;
      record.tagozat_label = tagozatName;
      record.is_student = true;
      record.warnings = [];
    }
    renderRows();
    showTagMessage(`${selectedRecords.length} diákhoz rendeltük hozzá: ${tagozatName}.`, true);
  });

  textarea.addEventListener("input", clearPreview);
  sourceCheckboxes.forEach((checkbox) => checkbox.addEventListener("change", clearPreview));
})();
