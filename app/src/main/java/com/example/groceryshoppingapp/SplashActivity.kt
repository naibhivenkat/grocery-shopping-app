//package com.example.groceryshoppingapp
//
//import android.content.Intent
//import android.os.Bundle
//import android.os.Handler
//import android.os.Looper
//import android.view.Gravity
//import android.widget.LinearLayout
//import android.widget.TextView
//import androidx.appcompat.app.AppCompatActivity
//import com.example.groceryshoppingapp.utils.SessionManager
//
//class SplashActivity : AppCompatActivity() {
//    override fun onCreate(savedInstanceState: Bundle?) {
//        super.onCreate(savedInstanceState)
//
//        // Layout setup
//        val layout = LinearLayout(this).apply {
//            orientation = LinearLayout.VERTICAL
//            gravity = Gravity.CENTER
//            layoutParams = LinearLayout.LayoutParams(
//                LinearLayout.LayoutParams.MATCH_PARENT,
//                LinearLayout.LayoutParams.MATCH_PARENT
//            )
//        }
//
//        val welcomeText = TextView(this).apply {
//            textSize = 22f
//            text = when (BuildConfig.APP_ROLE) {
//                "customer" -> "Welcome to Customer App"
//                "shopowner" -> "Welcome to Shop Owner App"
//                else -> "Welcome to Grocery App"
//            }
//            gravity = Gravity.CENTER
//        }
//
//        layout.addView(welcomeText)
//        setContentView(layout)
//
//        Handler(Looper.getMainLooper()).postDelayed({
//            if (SessionManager.isLoggedIn(this)) {
//                val role = SessionManager.getRole(this)
//                when (role) {
//                    "customer" -> startActivity(Intent(this, CustomerHomeActivity::class.java))
//                    "shopowner" -> startActivity(Intent(this, ShopOwnerDashboardActivity::class.java))
//                    else -> startActivity(Intent(this, LoginActivity::class.java))
//                }
//            } else {
//                startActivity(Intent(this, LoginActivity::class.java))
//            }
//            finish()
//        }, 2000)
//    }
//}
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
import com.google.firebase.auth.FirebaseAuth
import android.util.Log

class SplashActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // FIRST → Ensure Firebase Auth (MUST be before any Firestore reads)
        ensureFirebaseAuth()

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


    /**
     * Ensure Firebase Anonymous Authentication
     * This is required for Firestore rules using request.auth != null
     */
    private fun ensureFirebaseAuth() {
        val auth = FirebaseAuth.getInstance()

        if (auth.currentUser == null) {
            auth.signInAnonymously()
                .addOnSuccessListener {
                    Log.d("FIREBASE_AUTH", "Signed in anonymously: ${auth.currentUser?.uid}")
                }
                .addOnFailureListener {
                    Log.e("FIREBASE_AUTH", "Anonymous auth FAILED: ${it.message}")
                }
        } else {
            Log.d("FIREBASE_AUTH", "Already signed in: ${auth.currentUser?.uid}")
        }
    }
}
