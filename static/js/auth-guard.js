/* Si la sesión caduca, cualquier llamada a la API devuelve 401: llevamos al login
   conservando la página actual. Script clásico, se carga antes que el resto. */
(function () {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async function (...args) {
    const res = await originalFetch(...args);
    if (res.status === 401 && !location.pathname.startsWith('/login')) {
      location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
    }
    return res;
  };
})();
