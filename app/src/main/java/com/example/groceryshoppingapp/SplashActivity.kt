package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.utils.SessionManager

class SplashActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Layout setup
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.MATCH_PARENT
            )
        }

        val welcomeText = TextView(this).apply {
            textSize = 22f
            text = when (BuildConfig.APP_ROLE) {
                "customer" -> "Welcome to Customer App"
                "shopowner" -> "Welcome to Shop Owner App"
                else -> "Welcome to Grocery App"
            }
            gravity = Gravity.CENTER
        }

        layout.addView(welcomeText)
        setContentView(layout)

        Handler(Looper.getMainLooper()).postDelayed({
            if (SessionManager.isLoggedIn(this)) {
                val role = SessionManager.getRole(this)
                when (role) {
                    "customer" -> startActivity(Intent(this, CustomerHomeActivity::class.java))
                    "shopowner" -> startActivity(Intent(this, ShopOwnerDashboardActivity::class.java))
                    else -> startActivity(Intent(this, LoginActivity::class.java))
                }
            } else {
                startActivity(Intent(this, LoginActivity::class.java))
            }
            finish()
        }, 2000)
    }
}
