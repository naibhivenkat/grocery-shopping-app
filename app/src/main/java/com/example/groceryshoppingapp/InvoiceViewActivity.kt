package com.example.groceryshoppingapp

import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

class InvoiceViewActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_invoice_view)

        val webView = findViewById<WebView>(R.id.webViewInvoice)
        val orderId = intent.getStringExtra("order_id")

        webView.settings.javaScriptEnabled = true
        webView.settings.loadWithOverviewMode = true
        webView.settings.useWideViewPort = true

        // 👇 Ensures links and JS run inside same WebView
        webView.webViewClient = WebViewClient()

        // ✅ Add JS interface so HTML button can call Android's back
        webView.addJavascriptInterface(object {
            @JavascriptInterface
            fun goBackToApp() {
                runOnUiThread {
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        }, "AndroidApp")

        val backendBaseUrl = "https://grocery-backend-956424262985.asia-south1.run.app/"
        val invoiceUrl = "$backendBaseUrl/api/invoice_html/$orderId"

        webView.loadUrl(invoiceUrl)
    }
}
