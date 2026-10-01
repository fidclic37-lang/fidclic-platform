import { lazy } from 'react';

/* Every page is its own file, downloaded when it is first opened — so the
   login, a customer's card or the scan page no longer carry the whole app.
   After a deploy, a tab that stayed open still asks for the previous files,
   which are gone: the page then reloads once to pick up the new ones. */
const FLAG = 'fidclic:chunk-reload';

export default function lazyPage(load) {
  return lazy(() => load()
    .then((m) => { try { sessionStorage.removeItem(FLAG); } catch (e) { /* private mode */ } return m; })
    .catch((err) => {
      let tried = false;
      try { tried = sessionStorage.getItem(FLAG) === '1'; } catch (e) { /* private mode */ }
      if (!tried) {
        try { sessionStorage.setItem(FLAG, '1'); } catch (e) { /* private mode */ }
        window.location.reload();
        return new Promise(() => {});
      }
      throw err;
    }));
}
