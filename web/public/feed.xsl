<?xml version="1.0" encoding="utf-8"?>
<!-- Shown when a person opens the events feed in a browser. Feed readers use the feed itself and ignore this. -->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:a="http://www.w3.org/2005/Atom">
  <xsl:output method="html" encoding="utf-8" doctype-system="about:legacy-compat"/>
  <xsl:template match="/a:feed">
    <html lang="en">
      <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title>Events feed | Routeboard</title>
        <style>
          body { margin: 0; background: #eceff1; color: #101820; font: 17px/1.55 "Overpass", "Helvetica Neue", Arial, sans-serif; }
          header { background: #ffd200; border-bottom: 3px solid #101820; padding: 16px 20px; font-weight: 800; font-size: 20px; }
          header a { color: #101820; text-decoration: none; }
          main { max-width: 820px; margin: 0 auto; padding: 32px 20px 64px; }
          h1 { font-size: 40px; line-height: 1.05; margin: 0 0 12px; }
          p.lead { font-size: 19px; margin: 0 0 8px; max-width: 60ch; }
          code { background: #fff; border: 2px solid #101820; padding: 6px 10px; display: inline-block; margin: 8px 0 24px; font-size: 15px; word-break: break-all; }
          ol { list-style: none; margin: 0; padding: 0; background: #14181c; border-radius: 3px; }
          li { border-top: 1px solid #2a3037; }
          li:first-child { border-top: 0; }
          li a { display: grid; grid-template-columns: 150px 1fr; gap: 14px; padding: 13px 18px; color: #fff; text-decoration: none; }
          li a:hover { background: #20262c; }
          time { color: #ffd200; font-family: ui-monospace, Menlo, monospace; font-size: 14px; padding-top: 3px; }
          b { display: block; font-weight: 600; }
          span { color: #b9c1c8; font-size: 15px; }
          @media (max-width: 560px) { li a { grid-template-columns: 1fr; gap: 2px; } h1 { font-size: 30px; } }
        </style>
      </head>
      <body>
        <header><a href="/">Routeboard</a></header>
        <main>
          <h1>Events feed</h1>
          <p class="lead">This address is a feed. Paste it into a feed reader and new events will arrive there by themselves. The latest are listed below; times are UTC.</p>
          <code><xsl:value-of select="a:id"/>api/events.atom</code>
          <ol>
            <xsl:for-each select="a:entry">
              <li>
                <a href="{a:link/@href}">
                  <time><xsl:value-of select="concat(substring(a:updated, 1, 10), ' ', substring(a:updated, 12, 5))"/></time>
                  <div><b><xsl:value-of select="a:title"/></b><span><xsl:value-of select="a:summary"/></span></div>
                </a>
              </li>
            </xsl:for-each>
          </ol>
          <p class="lead" style="margin-top:24px"><a href="/events">Back to all events</a></p>
        </main>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
