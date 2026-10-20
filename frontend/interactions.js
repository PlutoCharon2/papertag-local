// Search overlays the current library view; clearing it restores that view.
(() => {
  const input = $('#search');
  const toggles = ['sameClaim','reviewedOnly','pendingOnly','favoritesOnly','showVersions'];
  let beforeSearch = null, timer, composing = false, revision = 0;
  function remember() {
    if (beforeSearch || !input.value) return;
    beforeSearch = {filters:JSON.parse(JSON.stringify(state.filters)), selected:state.selected,
      scroll:$('.paper-column').scrollTop, detailScroll:$('#detail').scrollTop,
      toggles:Object.fromEntries(toggles.map(id=>[id,$('#'+id).checked]))};
  }
  async function update() {
    const current = ++revision;
    if (!input.value && beforeSearch) {
      const previous = beforeSearch; beforeSearch = null;
      state.filters = previous.filters;
      for (const [id,value] of Object.entries(previous.toggles)) $('#'+id).checked = value;
      await loadOntology();
      if (current !== revision) return;
      await loadPapers();
      if (current !== revision) return;
      if (previous.selected && state.selected !== previous.selected) await loadDetail(previous.selected);
      if (current !== revision) return;
      $('.paper-column').scrollTop = previous.scroll;
      $('#detail').scrollTop = previous.detailScroll;
    } else await loadPapers();
  }
  function schedule() {
    remember(); clearTimeout(timer); revision++;
    // Invalidate pending list responses as soon as the input changes.
    state.paperRequest = (state.paperRequest || 0) + 1;
    if (!composing) timer = setTimeout(action(update), input.value ? 180 : 0);
  }
  input.addEventListener('compositionstart',()=>{composing=true;clearTimeout(timer)});
  input.addEventListener('compositionend',()=>{composing=false;schedule()});
  input.addEventListener('input',schedule);
  input.onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing){clearTimeout(timer);remember();action(update)();}};
  $('#searchButton').onclick=action(async()=>{clearTimeout(timer);remember();await update()});
  $('#clearFilters').addEventListener('click',()=>{clearTimeout(timer);revision++;beforeSearch=null;});
  window.openTaskPaper = action(async id => {
    clearTimeout(timer); revision++; beforeSearch=null;
    input.value=''; state.filters={};
    for (const name of toggles) $('#'+name).checked=false;
    document.body.classList.remove('reading-focus');
    showPage('library');
    await loadOntology(); await loadPapers(); await loadDetail(Number(id));
    $('#papers').querySelector(`[data-id="${Number(id)}"]`)?.scrollIntoView({block:'nearest'});
  });
  $('#aiJobs').addEventListener('click',event=>{
    const target=event.target.closest('[data-open-paper]');
    if(target) openTaskPaper(Number(target.dataset.openPaper));
  });
})();
