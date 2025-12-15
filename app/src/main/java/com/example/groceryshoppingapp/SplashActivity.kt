////package com.example.groceryshoppingapp
////
////import android.content.Intent
////import android.os.Bundle
////import android.os.Handler
////import android.os.Looper
////import android.view.Gravity
////import android.widget.LinearLayout
////import android.widget.TextView
////import androidx.appcompat.app.AppCompatActivity
////import com.example.groceryshoppingapp.utils.SessionManager
////
////class SplashActivity : AppCompatActivity() {
////    override fun onCreate(savedInstanceState: Bundle?) {
////        super.onCreate(savedInstanceState)
////
////        // Layout setup
////        val layout = LinearLayout(this).apply {
////            orientation = LinearLayout.VERTICAL
////            gravity = Gravity.CENTER
////            layoutParams = LinearLayout.LayoutParams(
////                LinearLayout.LayoutParams.MATCH_PARENT,
////                LinearLayout.LayoutParams.MATCH_PARENT
////            )
////        }
////
////        val welcomeText = TextView(this).apply {
////            textSize = 22f
////            text = when (BuildConfig.APP_ROLE) {
////                "customer" -> "Welcome to Customer App"
////                "shopowner" -> "Welcome to Shop Owner App"
////                else -> "Welcome to Grocery App"
////            }
////            gravity = Gravity.CENTER
////        }
////
////        layout.addView(welcomeText)
////        setContentView(layout)
////
////        Handler(Looper.getMainLooper()).postDelayed({
////            if (SessionManager.isLoggedIn(this)) {
////                val role = SessionManager.getRole(this)
////                when (role) {
////                    "customer" -> startActivity(Intent(this, CustomerHomeActivity::class.java))
////                    "shopowner" -> startActivity(Intent(this, ShopOwnerDashboardActivity::class.java))
////                    else -> startActivity(Intent(this, LoginActivity::class.java))
////                }
////            } else {
////                startActivity(Intent(this, LoginActivity::class.java))
////            }
////            finish()
////        }, 2000)
////    }
////}
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
//import com.google.firebase.auth.FirebaseAuth
//import android.util.Log
//
//class SplashActivity : AppCompatActivity() {
//
//    override fun onCreate(savedInstanceState: Bundle?) {
//        super.onCreate(savedInstanceState)
//
//        // FIRST → Ensure Firebase Auth (MUST be before any Firestore reads)
//        ensureFirebaseAuth()
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
//
//
//    /**
//     * Ensure Firebase Anonymous Authentication
//     * This is required for Firestore rules using request.auth != null
//     */
//    private fun ensureFirebaseAuth() {
//        val auth = FirebaseAuth.getInstance()
//
//        if (auth.currentUser == null) {
//            auth.signInAnonymously()
//                .addOnSuccessListener {
//                    Log.d("FIREBASE_AUTH", "Signed in anonymously: ${auth.currentUser?.uid}")
//                }
//                .addOnFailureListener {
//                    Log.e("FIREBASE_AUTH", "Anonymous auth FAILED: ${it.message}")
//                }
//        } else {
//            Log.d("FIREBASE_AUTH", "Already signed in: ${auth.currentUser?.uid}")
//        }
//    }
//}


package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.firebase.auth.FirebaseAuth
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class SplashActivity : AppCompatActivity() {

    private val api by lazy {
        RetrofitClient.getInstance(this).create(ApiService::class.java)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        ensureFirebaseAuth()
        showSplashScreen()

        // Delay just to show splash text
        Handler(Looper.getMainLooper()).postDelayed({
            checkCloudRunStatus()
        }, 1200)
    }

    // ---------------------------------------------------------
    // 1) Firebase Anonymous Login
    // ---------------------------------------------------------
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
        }
    }

    // ---------------------------------------------------------
    // 2) Create basic splash layout
    // ---------------------------------------------------------
    private fun showSplashScreen() {
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
    }

    // ---------------------------------------------------------
    // 3) Cloud Run Health Check
    // ---------------------------------------------------------
    private fun checkCloudRunStatus() {
        api.healthCheck().enqueue(object : Callback<Map<String, String>> {
            override fun onResponse(
                call: Call<Map<String, String>>,
                response: Response<Map<String, String>>
            ) {
                if (response.isSuccessful) {
                    proceedToNextScreen()
                } else {
                    showServerOfflineScreen("Server unavailable right now.")
                }
            }

            override fun onFailure(call: Call<Map<String, String>>, t: Throwable) {
                showServerOfflineScreen("Server offline. Please check internet or try again.")
            }
        })
    }

    // ---------------------------------------------------------
    // 4) Navigation after server online
    // ---------------------------------------------------------
    private fun proceedToNextScreen() {
        if (SessionManager.isLoggedIn(this)) {
            when (SessionManager.getRole(this)) {
                "customer" -> startActivity(Intent(this, CustomerHomeActivity::class.java))
                "shopowner" -> startActivity(Intent(this, ShopOwnerDashboardActivity::class.java))
                else -> startActivity(Intent(this, LoginActivity::class.java))
            }
        } else {
            startActivity(Intent(this, LoginActivity::class.java))
        }
        finish()
    }

    // ---------------------------------------------------------
    // 5) Server Offline UI + Retry Button
    // ---------------------------------------------------------
    private fun showServerOfflineScreen(message: String) {
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
        }

        val msgView = TextView(this).apply {
            text = message
            textSize = 18f
            gravity = Gravity.CENTER
        }

        val retry = TextView(this).apply {
            text = "Retry"
            textSize = 20f
            setPadding(20, 40, 20, 40)
            setOnClickListener {
                Toast.makeText(this@SplashActivity, "Checking server...", Toast.LENGTH_SHORT).show()
                checkCloudRunStatus()
            }
        }

        layout.addView(msgView)
        layout.addView(retry)
        setContentView(layout)
    }
}
