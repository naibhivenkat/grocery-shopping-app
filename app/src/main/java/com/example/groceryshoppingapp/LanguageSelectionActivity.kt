package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.utils.SessionManager

class LanguageSelectionActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        // apply whatever is currently saved (default en) so UI looks consistent
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
        // persist
        SessionManager.setLanguageCode(this, code)
        SessionManager.setLanguageSelected(this, true)

        // apply immediately
        baseContext.applyLanguage(code)

        // Go back to the main screen based on role
        val role = intent.getStringExtra("pendingRole")?.lowercase()
        when (role) {
            "customer" -> {
                startActivity(Intent(this, CustomerHomeActivity::class.java))
            }

            "shopowner" -> {
                startActivity(Intent(this, ShopOwnerDashboardActivity::class.java))
            }

            else -> {
                // Fallback to previous screen
                onBackPressedDispatcher.onBackPressed()
                return
            }
        }
        finish()
    }
}
