const escape = value => value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (request.method !== 'GET' || !['/v1/guide','/'].includes(path)) return new Response('Not found', {status:404});
    const data = await env.DB.prepare("SELECT content FROM guides WHERE id = 'academy'").first('content');
    if (!data) return new Response('Temporarily unavailable',{status:503});
    if (path==='/v1/guide') return Response.json(JSON.parse(data),{headers:{'Cache-Control':'public, max-age=300'}});
    const sections = JSON.parse(data).map(row=>{
      const expired = row.ends && Date.now()>=Date.parse(row.ends);
      const sources = row.sources.filter(s=>!s.url.startsWith(new URL(request.url).origin)).map(s=>'<a href="'+escape(s.url)+'">'+escape(s.title)+'</a>').join(' · ');
      return '<section id="'+escape(row.id)+'"><h2>'+escape(row.id.replaceAll('-',' '))+'</h2><p>'+escape(expired ? row.expired_en : row.en)+'</p><p>'+sources+'</p></section>';
    });
    return new Response('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Towards AI Academy guidance</title><main style="max-width:44rem;margin:2rem auto;padding:1rem;font:17px/1.5 system-ui"><h1>Towards AI Academy guidance</h1>'+sections.join('')+'</main></html>',{headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-cache'}});
  }
};
