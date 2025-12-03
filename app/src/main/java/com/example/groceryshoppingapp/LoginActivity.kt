//package com.example.groceryshoppingapp
//
//import android.annotation.SuppressLint
//import android.content.Intent
//import android.os.Bundle
//import android.util.Log
//import android.view.View
//import android.widget.*
//import androidx.appcompat.app.AppCompatActivity
//import com.example.groceryshoppingapp.models.LoginRequest
//import com.example.groceryshoppingapp.models.LoginResponse
//import com.example.groceryshoppingapp.models.Item
//import com.example.groceryshoppingapp.network.ApiService
//import com.example.groceryshoppingapp.network.RetrofitClient
//import com.example.groceryshoppingapp.utils.SessionManager
//import com.google.firebase.messaging.FirebaseMessaging
//import kotlinx.coroutines.*
//import retrofit2.Call
//import retrofit2.Callback
//import retrofit2.Response
//
//class LoginActivity : AppCompatActivity() {
//
//    private lateinit var usernameEdit: EditText
//    private lateinit var passwordEdit: EditText
//    private lateinit var loginButton: Button
//    private lateinit var registerText: TextView
//    private lateinit var titleText: TextView
//    private lateinit var errorText: TextView
//    private lateinit var forgotPasswordText: TextView
//    private lateinit var helpText: TextView
//    private lateinit var progressBar: ProgressBar
//
//    private val appRole by lazy { BuildConfig.APP_ROLE.lowercase() }
//    private val api by lazy { RetrofitClient.getInstance(this).create(ApiService::class.java) }
//
//    override fun onCreate(savedInstanceState: Bundle?) {
//        LanguageManager.applySavedLanguage(this)
//        super.onCreate(savedInstanceState)
//        setContentView(R.layout.activity_login)
//
//        titleText = findViewById(R.id.tv_login_title)
//        usernameEdit = findViewById(R.id.et_username)
//        passwordEdit = findViewById(R.id.et_password)
//        loginButton = findViewById(R.id.btn_login)
//        registerText = findViewById(R.id.tv_register)
//        errorText = findViewById(R.id.tv_error_message)
//        forgotPasswordText = findViewById(R.id.tv_forgot_password)
//        helpText = findViewById(R.id.tv_help)
//        progressBar = findViewById(R.id.progress_bar)
//
//        titleText.text = when (appRole) {
//            "customer" -> getString(R.string.customer_login)
//            "shopowner" -> getString(R.string.shop_owner_login)
//            else -> getString(R.string.login)
//        }
//
//        loginButton.setOnClickListener {
//            val username = usernameEdit.text.toString().trim()
//            val password = passwordEdit.text.toString().trim()
//
//            errorText.visibility = View.GONE
//
//            if (username.isEmpty() || password.isEmpty()) {
//                errorText.text = getString(R.string.enter_username_password)
//                errorText.visibility = View.VISIBLE
//                return@setOnClickListener
//            }
//
//            doLogin(username, password)
//        }
//
//        registerText.setOnClickListener { checkServerBeforeRegister() }
//
//        forgotPasswordText.setOnClickListener {
//            startActivity(Intent(this, ForgotPasswordActivity::class.java))
//        }
//
//        helpText.setOnClickListener {
//            startActivity(Intent(this, HelpActivity::class.java))
//        }
//    }
//
//    private fun doLogin(username: String, password: String) {
//
//        progressBar.visibility = View.VISIBLE
//        loginButton.isEnabled = false
//        errorText.visibility = View.GONE
//
//        api.login(LoginRequest(username, password))
//            .enqueue(object : Callback<LoginResponse> {
//
//                @SuppressLint("StringFormatInvalid")
//                override fun onResponse(
//                    call: Call<LoginResponse>,
//                    response: Response<LoginResponse>
//                ) {
//                    progressBar.visibility = View.GONE
//                    loginButton.isEnabled = true
//
//                    try {
//                        val loginResponse = response.body()
//
//                        when {
//                            !response.isSuccessful -> {
//                                errorText.text = "Server temporarily unavailable."
//                                errorText.visibility = View.VISIBLE
//                            }
//
//                            loginResponse == null -> {
//                                errorText.text = "Server temporarily unavailable."
//                                errorText.visibility = View.VISIBLE
//                            }
//
//                            loginResponse.success != true -> {
//                                errorText.text = getString(R.string.invalid_username_password)
//                                errorText.visibility = View.VISIBLE
//                            }
//
//                            else -> {
//                                val user = loginResponse.user
//                                val loginRole = user?.role?.lowercase()?.trim()
//
//                                // Save token
//                                loginResponse.token?.let {
//                                    SessionManager.setAuthToken(this@LoginActivity, it)
//                                }
//
//                                // Role mismatch block
//                                if (loginRole != appRole) {
//                                    errorText.text = getString(
//                                        R.string.role_mismatch,
//                                        appRole.replaceFirstChar { it.uppercase() })
//                                    errorText.visibility = View.VISIBLE
//                                    return
//                                }
//
//                                // Save basic profile in local storage
//                                SessionManager.saveLogin(
//                                    this@LoginActivity,
//                                    user?.username ?: "",
//                                    loginRole ?: ""
//                                )
//
//                                SessionManager.saveUserProfile(
//                                    this@LoginActivity,
//                                    user?.fullName ?: "",
//                                    user?.address ?: "",
//                                    user?.phone ?: "",
//                                    user?.email ?: "",
//                                    user?.location ?: "",
//                                    user?.photoBase64 ?: ""
//                                )
//
//                                // Save user IDs depending on role
//                                user?.customerId?.let { SessionManager.setCustomerId(this@LoginActivity, it) }
//                                user?.shopkeeperId?.let { SessionManager.setShopkeeperId(this@LoginActivity, it) }
//                                // ⭐ NEW — save Firestore real user ID (for wallet)
//                                user?.firebaseId?.let { SessionManager.setFirebaseId(this@LoginActivity, it) }
//
//
//                                // Save shop info for shopowner
//                                user?.shop?.id?.let { shopDocId ->
//                                    SessionManager.setShopId(this@LoginActivity, shopDocId)
//                                    SessionManager.setShopInfo(
//                                        this@LoginActivity,
//                                        shopDocId,
//                                        user.shop?.name ?: ""
//                                    )
//                                }
//
//                                // ⭐ FIX ADDED — minimal change
//                                val hasItems = user?.hasItems ?: true
//                                SessionManager.setHasItemsAdded(this@LoginActivity, hasItems)
//
//                                // Preload data
//                                if (loginRole == "customer") {
//                                    preloadShopsAndItems()
//                                    preloadOrders("customer")
//                                }
//
//                                // ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐
//                                // FCM TOKEN REGISTRATION FIX
//                                // ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐
//                                FirebaseMessaging.getInstance().token
//                                    .addOnCompleteListener { task ->
//                                        if (!task.isSuccessful) {
//                                            Log.w("FCM", "Failed to get token")
//                                            return@addOnCompleteListener
//                                        }
//
//                                        val fcmToken = task.result
//                                        Log.d("FCM", "Token = $fcmToken")
//
//                                        val realUserId =
//                                            if (loginRole == "customer")
//                                                user?.customerId
//                                            else
//                                                user?.shopkeeperId
//
//                                        Log.d("FCM", "Sending FCM token for userId=$realUserId")
//
//                                        if (!realUserId.isNullOrEmpty()) {
//                                            CoroutineScope(Dispatchers.IO).launch {
//                                                try {
//                                                    val resp = api.registerFcmToken(
//                                                        mapOf(
//                                                            "user_id" to realUserId,
//                                                            "role" to loginRole,
//                                                            "token" to fcmToken
//                                                        )
//                                                    ).execute()
//
//                                                    if (resp.isSuccessful) {
//                                                        Log.d("FCM", "FCM token saved!")
//                                                    } else {
//                                                        Log.e("FCM", "Failed save: ${resp.errorBody()?.string()}")
//                                                    }
//                                                } catch (e: Exception) {
//                                                    Log.e("FCM", "Error saving token: ${e.message}")
//                                                }
//                                            }
//                                        }
//                                    }
//
//                                // Redirect
//                                when (loginRole) {
//                                    "customer" -> {
//                                        startActivity(Intent(this@LoginActivity, CustomerHomeActivity::class.java))
//                                    }
//
//                                    "shopowner" -> {
//                                        if (SessionManager.hasShopWithItems(this@LoginActivity)) {
//                                            startActivity(Intent(this@LoginActivity, ShopOwnerDashboardActivity::class.java))
//                                        } else {
//                                            startActivity(Intent(this@LoginActivity, AddItemsActivity::class.java))
//                                        }
//                                    }
//
//                                    else -> {
//                                        errorText.text = getString(R.string.unknown_user_role)
//                                        errorText.visibility = View.VISIBLE
//                                        return
//                                    }
//                                }
//
//                                finish()
//                            }
//                        }
//
//                    } catch (e: Exception) {
//                        Log.e("LoginDebug", "Exception in onResponse", e)
//                        errorText.text = "Server temporarily unavailable."
//                        errorText.visibility = View.VISIBLE
//                    }
//                }
//
//                override fun onFailure(call: Call<LoginResponse>, t: Throwable) {
//                    progressBar.visibility = View.GONE
//                    loginButton.isEnabled = true
//
//                    val message = when (t) {
//                        is java.net.UnknownHostException ->
//                            "Server offline. Check your internet."
//
//                        is java.net.ConnectException ->
//                            "Cannot connect to server."
//
//                        is java.net.SocketTimeoutException ->
//                            "Server timed out."
//
//                        else ->
//                            "Login failed: ${t.localizedMessage ?: "Unknown error"}"
//                    }
//
//                    errorText.text = message
//                    errorText.visibility = View.VISIBLE
//                }
//            })
//    }
//
//    private fun preloadShopsAndItems() {
//        CoroutineScope(Dispatchers.IO).launch {
//            try {
//                val shopsResp = api.getAllShops().execute()
//                if (shopsResp.isSuccessful && shopsResp.body() != null) {
//                    val shops = shopsResp.body()!!
//                    SessionManager.cacheShopList(this@LoginActivity, shops)
//
//                    val allItems = mutableMapOf<String, List<Item>>()
//
//                    shops.forEach { shop ->
//                        try {
//                            val itemsResp = api.getItems(shop.id).execute()
//                            if (itemsResp.isSuccessful && itemsResp.body() != null) {
//                                allItems[shop.id] = itemsResp.body()!!.items
//                            }
//                        } catch (_: Exception) {}
//                    }
//
//                    SessionManager.cacheItemsByShop(this@LoginActivity, allItems)
//                }
//            } catch (_: Exception) {}
//        }
//    }
//
//    private fun preloadOrders(role: String) {
//        CoroutineScope(Dispatchers.IO).launch {
//            try {
//                when (role) {
//                    "customer" -> {
//                        val customerId = SessionManager.getCustomerId(this@LoginActivity)
//                        if (!customerId.isNullOrEmpty()) {
//                            val resp = api.getCustomerOrders(customerId).execute()
//                            if (resp.isSuccessful && resp.body() != null) {
//                                SessionManager.cacheCustomerOrders(this@LoginActivity, resp.body()!!)
//                            }
//                        }
//                    }
//                }
//            } catch (_: Exception) {}
//        }
//    }
//
//    private fun checkServerBeforeRegister() {
//        progressBar.visibility = View.VISIBLE
//        registerText.isEnabled = false
//
//        api.healthCheck()
//            .enqueue(object : Callback<Map<String, String>> {
//
//                override fun onResponse(
//                    call: Call<Map<String, String>>,
//                    response: Response<Map<String, String>>
//                ) {
//                    progressBar.visibility = View.GONE
//                    registerText.isEnabled = true
//
//                    if (response.isSuccessful) {
//                        startActivity(Intent(this@LoginActivity, RegisterActivity::class.java))
//                    } else {
//                        Toast.makeText(
//                            this@LoginActivity,
//                            "Server unavailable right now.",
//                            Toast.LENGTH_SHORT
//                        ).show()
//                    }
//                }
//
//                override fun onFailure(call: Call<Map<String, String>>, t: Throwable) {
//                    progressBar.visibility = View.GONE
//                    registerText.isEnabled = true
//                    Toast.makeText(
//                        this@LoginActivity,
//                        "Server offline.",
//                        Toast.LENGTH_SHORT
//                    ).show()
//                }
//            })
//    }
//}


package com.example.groceryshoppingapp

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.models.LoginRequest
import com.example.groceryshoppingapp.models.LoginResponse
import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.*
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class LoginActivity : AppCompatActivity() {

    private lateinit var usernameEdit: EditText
    private lateinit var passwordEdit: EditText
    private lateinit var loginButton: Button
    private lateinit var registerText: TextView
    private lateinit var titleText: TextView
    private lateinit var errorText: TextView
    private lateinit var forgotPasswordText: TextView
    private lateinit var helpText: TextView
    private lateinit var progressBar: ProgressBar

    private val appRole by lazy { BuildConfig.APP_ROLE.lowercase() }
    private val api by lazy { RetrofitClient.getInstance(this).create(ApiService::class.java) }

    override fun onCreate(savedInstanceState: Bundle?) {
        LanguageManager.applySavedLanguage(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        titleText = findViewById(R.id.tv_login_title)
        usernameEdit = findViewById(R.id.et_username)
        passwordEdit = findViewById(R.id.et_password)
        loginButton = findViewById(R.id.btn_login)
        registerText = findViewById(R.id.tv_register)
        errorText = findViewById(R.id.tv_error_message)
        forgotPasswordText = findViewById(R.id.tv_forgot_password)
        helpText = findViewById(R.id.tv_help)
        progressBar = findViewById(R.id.progress_bar)

        titleText.text = when (appRole) {
            "customer" -> getString(R.string.customer_login)
            "shopowner" -> getString(R.string.shop_owner_login)
            else -> getString(R.string.login)
        }

        loginButton.setOnClickListener {
            val username = usernameEdit.text.toString().trim()
            val password = passwordEdit.text.toString().trim()

            errorText.visibility = View.GONE

            if (username.isEmpty() || password.isEmpty()) {
                errorText.text = getString(R.string.enter_username_password)
                errorText.visibility = View.VISIBLE
                return@setOnClickListener
            }

            doLogin(username, password)
        }

        registerText.setOnClickListener { checkServerBeforeRegister() }
        forgotPasswordText.setOnClickListener {
            startActivity(Intent(this, ForgotPasswordActivity::class.java))
        }
        helpText.setOnClickListener {
            startActivity(Intent(this, HelpActivity::class.java))
        }
    }

    private fun doLogin(username: String, password: String) {

        progressBar.visibility = View.VISIBLE
        loginButton.isEnabled = false
        errorText.visibility = View.GONE

        api.login(LoginRequest(username, password))
            .enqueue(object : Callback<LoginResponse> {

                @SuppressLint("StringFormatInvalid")
                override fun onResponse(call: Call<LoginResponse>, response: Response<LoginResponse>) {

                    progressBar.visibility = View.GONE
                    loginButton.isEnabled = true

                    try {

                        // ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐
                        // ⭐ IMPORTANT FIX: HANDLE WRONG PASSWORD / WRONG USERID
                        // ⭐ If backend returns 401 or 404, response.isSuccessful = false.
                        // ⭐ Instead of showing "Server unavailable", we read errorBody().
                        // ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐
                        if (!response.isSuccessful) {   // ⭐ CHANGED ERROR HANDLING
                            try {
                                val errorTextBody = response.errorBody()?.string() ?: ""
                                val msgLower = errorTextBody.lowercase()

                                val finalMessage =
                                    when {
                                        "user not found" in msgLower -> "User ID does not exist"
                                        "invalid password" in msgLower -> "Incorrect password"
                                        else -> "Login failed. Please try again."
                                    }

                                showError(finalMessage)   // ⭐ ADDED
                            } catch (e: Exception) {
                                showError("Server temporarily unavailable.")  // fallback
                            }
                            return
                        }
                        // ⭐ END OF FIX BLOCK


                        val loginResponse = response.body()
                        if (loginResponse == null) {
                            showError("Server temporarily unavailable.")
                            return
                        }

                        // SUCCESS CASE
                        if (loginResponse.success != true) {
                            val serverMsg = loginResponse.message?.lowercase() ?: ""
                            val finalMessage =
                                when {
                                    "user not found" in serverMsg -> "User ID does not exist"
                                    "invalid password" in serverMsg -> "Incorrect password"
                                    else -> getString(R.string.invalid_username_password)
                                }
                            showError(finalMessage)
                            return
                        }

                        val user = loginResponse.user
                        val loginRole = user?.role?.lowercase()?.trim()

                        // Save token
                        loginResponse.token?.let {
                            SessionManager.setAuthToken(this@LoginActivity, it)
                        }

                        // ROLE MISMATCH
                        if (loginRole != appRole) {
                            showError(
                                getString(
                                    R.string.role_mismatch,
                                    appRole.replaceFirstChar { it.uppercase() })
                            )
                            return
                        }

                        // SAVE user login & profile
                        SessionManager.saveLogin(
                            this@LoginActivity,
                            user?.username ?: "",
                            loginRole ?: ""
                        )

                        SessionManager.saveUserProfile(
                            this@LoginActivity,
                            user?.fullName ?: "",
                            user?.address ?: "",
                            user?.phone ?: "",
                            user?.email ?: "",
                            user?.location ?: "",
                            user?.photoBase64 ?: ""
                        )

                        // Save IDs
                        user?.customerId?.let { SessionManager.setCustomerId(this@LoginActivity, it) }
                        user?.shopkeeperId?.let { SessionManager.setShopkeeperId(this@LoginActivity, it) }
                        user?.firebaseId?.let { SessionManager.setFirebaseId(this@LoginActivity, it) }

                        // Save Shop info
                        user?.shop?.id?.let { shopDocId ->
                            SessionManager.setShopId(this@LoginActivity, shopDocId)
                            SessionManager.setShopInfo(
                                this@LoginActivity,
                                shopDocId,
                                user.shop?.name ?: ""
                            )
                        }

                        val hasItems = user?.hasItems ?: true
                        SessionManager.setHasItemsAdded(this@LoginActivity, hasItems)

                        if (loginRole == "customer") {
                            preloadShopsAndItems()
                            preloadOrders("customer")
                        }

                        // FCM TOKEN REGISTER
                        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
                            if (task.isSuccessful) {
                                val fcmToken = task.result
                                val realUserId =
                                    if (loginRole == "customer") user?.customerId else user?.shopkeeperId

                                if (!realUserId.isNullOrEmpty()) {
                                    CoroutineScope(Dispatchers.IO).launch {
                                        try {
                                            api.registerFcmToken(
                                                mapOf(
                                                    "user_id" to realUserId,
                                                    "role" to loginRole,
                                                    "token" to fcmToken
                                                )
                                            ).execute()
                                        } catch (_: Exception) {
                                        }
                                    }
                                }
                            }
                        }

                        // REDIRECT SCREEN
                        when (loginRole) {
                            "customer" -> startActivity(Intent(this@LoginActivity, CustomerHomeActivity::class.java))

                            "shopowner" -> {
                                if (SessionManager.hasShopWithItems(this@LoginActivity)) {
                                    startActivity(Intent(this@LoginActivity, ShopOwnerDashboardActivity::class.java))
                                } else {
                                    startActivity(Intent(this@LoginActivity, AddItemsActivity::class.java))
                                }
                            }

                            else -> showError(getString(R.string.unknown_user_role))
                        }

                        finish()

                    } catch (e: Exception) {
                        Log.e("LoginDebug", "Exception", e)
                        showError("Server temporarily unavailable.")
                    }
                }

                override fun onFailure(call: Call<LoginResponse>, t: Throwable) {
                    progressBar.visibility = View.GONE
                    loginButton.isEnabled = true

                    val message = when (t) {
                        is java.net.UnknownHostException -> "Server offline. Check your internet."
                        is java.net.ConnectException -> "Cannot connect to server."
                        is java.net.SocketTimeoutException -> "Server timed out."
                        else -> "Login failed: ${t.localizedMessage ?: "Unknown error"}"
                    }

                    showError(message)
                }
            })
    }

    private fun showError(msg: String) {
        errorText.text = msg
        errorText.visibility = View.VISIBLE
    }

    private fun preloadShopsAndItems() {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val shopsResp = api.getAllShops().execute()
                if (shopsResp.isSuccessful && shopsResp.body() != null) {
                    val shops = shopsResp.body()!!
                    SessionManager.cacheShopList(this@LoginActivity, shops)

                    val allItems = mutableMapOf<String, List<Item>>()

                    shops.forEach { shop ->
                        try {
                            val itemsResp = api.getItems(shop.id).execute()
                            if (itemsResp.isSuccessful && itemsResp.body() != null) {
                                allItems[shop.id] = itemsResp.body()!!.items
                            }
                        } catch (_: Exception) {
                        }
                    }

                    SessionManager.cacheItemsByShop(this@LoginActivity, allItems)
                }
            } catch (_: Exception) {
            }
        }
    }

    private fun preloadOrders(role: String) {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                if (role == "customer") {
                    val customerId = SessionManager.getCustomerId(this@LoginActivity)
                    if (!customerId.isNullOrEmpty()) {
                        val resp = api.getCustomerOrders(customerId).execute()
                        if (resp.isSuccessful && resp.body() != null) {
                            SessionManager.cacheCustomerOrders(this@LoginActivity, resp.body()!!)
                        }
                    }
                }
            } catch (_: Exception) {
            }
        }
    }

    private fun checkServerBeforeRegister() {
        progressBar.visibility = View.VISIBLE
        registerText.isEnabled = false

        api.healthCheck()
            .enqueue(object : Callback<Map<String, String>> {

                override fun onResponse(
                    call: Call<Map<String, String>>,
                    response: Response<Map<String, String>>
                ) {
                    progressBar.visibility = View.GONE
                    registerText.isEnabled = true

                    if (response.isSuccessful) {
                        startActivity(Intent(this@LoginActivity, RegisterActivity::class.java))
                    } else {
                        Toast.makeText(this@LoginActivity, "Server unavailable right now.", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<Map<String, String>>, t: Throwable) {
                    progressBar.visibility = View.GONE
                    registerText.isEnabled = true
                    Toast.makeText(this@LoginActivity, "Server offline.", Toast.LENGTH_SHORT).show()
                }
            })
    }
}

