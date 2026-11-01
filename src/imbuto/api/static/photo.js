// Enhancement only: without this file the form still uploads the full photo.
// Shrinks to 320px JPEG (about 12 KB, against 4 MB from a camera) and queues it when offline.
(function () {
  var form = document.getElementById('f'), input = document.getElementById('i');
  function open() {
    return new Promise(function (ok, no) {
      var r = indexedDB.open('imbuto', 1);
      r.onupgradeneeded = function () { r.result.createObjectStore('photos', { autoIncrement: true }); };
      r.onsuccess = function () { ok(r.result); }; r.onerror = no;
    });
  }
  function shrink(file) {
    return createImageBitmap(file).then(function (img) {
      var side = Math.min(img.width, img.height), c = document.createElement('canvas');
      c.width = c.height = 320;
      c.getContext('2d').drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, 320, 320);
      return new Promise(function (ok) { c.toBlob(ok, 'image/jpeg', 0.4); });
    });
  }
  // `sent` runs before the page is replaced, so the next page cannot resend the same photo.
  function send(blob, sent) {
    var d = new FormData(); d.append('image', blob, 'leaf.jpg');
    return fetch('/photo', { method: 'POST', body: d }).then(function (r) {
      if (!r.ok) throw new Error('upload failed');
      return r.text();
    }).then(function (h) {
      return Promise.resolve(sent && sent()).then(function () {
        document.open(); document.write(h); document.close();
      });
    });
  }
  function queue(blob) {
    return open().then(function (db) {
      return new Promise(function (ok) {
        var t = db.transaction('photos', 'readwrite'); t.objectStore('photos').add(blob); t.oncomplete = ok;
      });
    }).then(function () { document.getElementById('queued').hidden = false; });
  }
  function flush() {
    open().then(function (db) {
      var s = db.transaction('photos', 'readwrite').objectStore('photos'), r = s.openCursor();
      r.onsuccess = function () {
        var c = r.result; if (!c) return;
        var key = c.key, blob = c.value;
        send(blob, function () {
          return new Promise(function (ok) {
            var t = db.transaction('photos', 'readwrite');
            t.objectStore('photos').delete(key); t.oncomplete = ok;
          });
        }).catch(function () {});
      };
    });
  }
  form.addEventListener('submit', function (e) {
    var file = input.files[0];
    if (!file || !window.createImageBitmap) return;
    e.preventDefault();
    shrink(file).then(function (blob) {
      return navigator.onLine ? send(blob).catch(function () { return queue(blob); }) : queue(blob);
    }).catch(function () { form.submit(); });
  });
  addEventListener('online', flush);
  if (navigator.onLine) flush();
})();
