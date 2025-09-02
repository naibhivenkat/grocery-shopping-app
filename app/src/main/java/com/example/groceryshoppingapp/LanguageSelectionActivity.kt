package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.utils.SessionManager

class LanguageSelectionActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        LanguageManager.applySavedLanguage(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_language_selection)

        findViewById<Button>(R.id.btnKannada).setOnClickListener { select("kn") }
        findViewById<Button>(R.id.btnHindi).setOnClickListener { select("hi") }
        findViewById<Button>(R.id.btnTelugu).setOnClickListener { select("te") }
        findViewById<Button>(R.id.btnTamil).setOnClickListener { select("ta") }
        findViewById<Button>(R.id.btnMalayalam).setOnClickListener { select("ml") }
        findViewById<Button>(R.id.btnEnglish).setOnClickListener { select("en") }
    }

    private fun select(code: String) {
        // Save selected language
        SessionManager.setLanguageCode(this, code)
        SessionManager.setLanguageSelected(this, true)

        // ✅ Re-save login session (because app may restart after applyLanguage)
        val role = intent.getStringExtra("pendingRole")?.lowercase()
        val shopkeeperId = intent.getStringExtra("shopkeeperId")
        val customerId = intent.getStringExtra("customerId")

        role?.let {
            SessionManager.saveLogin(this, SessionManager.getUsername(this) ?: "", it)
        }
        customerId?.let { SessionManager.setCustomerId(this, it) }
        shopkeeperId?.let { SessionManager.setShopkeeperId(this, it) }

        // Apply immediately (may restart activity)
        baseContext.applyLanguage(code)

        // Redirect based on role
        when (role) {
            "customer" -> startActivity(Intent(this, CustomerHomeActivity::class.java))
            "shopowner" -> startActivity(Intent(this, ShopOwnerDashboardActivity::class.java))
            else -> onBackPressedDispatcher.onBackPressed()
        }
        finish()
    }

}
